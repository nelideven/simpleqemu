#!/usr/bin/env python3

'''
simpleqemu - A simple QEMU runner script as a libvirt alternative.
This program is free software; you can redistribute it and/or modify it under the terms of the GNU General Public License as published by the Free Software Foundation; either version 3.0 of the License, or (at your option) any later version.
This program is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU General Public License for more details.
You should have received a copy of the GNU General Public License along with this program; if not, see <https://www.gnu.org/licenses/>.
'''

import yaml, shlex, shutil, subprocess, os, sys, signal, time, socket, select, threading

def monitor_reader(sock):
    while True:
        try:
            data = sock.recv(4096).decode()
            for line in data.splitlines():
                if line.startswith("QEMU") or line.startswith("(qemu)"):
                    continue
                else:
                    print(line)
            time.sleep(0.1)  # prevent busy loop if monitor floods output
        except Exception:
            break

def get_vfio_group(pci_addr):
    path = f"/sys/bus/pci/devices/{pci_addr}/iommu_group"
    if os.path.islink(path):
        target = os.readlink(path)
        group_id = os.path.basename(target)
        return f"/dev/vfio/{group_id}"
    return None

def connect_monitor(path):
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.connect(path)
    return sock

def repl(sock, qemuproc):
    threading.Thread(target=monitor_reader, args=(sock,), daemon=True).start()
    os.system("clear")  # clear the screen for a cleaner REPL experience
    print("Welcome to simpleqemu monitor! Type 'help' to get started or enter any QEMU monitor command to send it directly.")
    while True:
        qcmd = ""
        try:
            line = input("qemu> ").strip()
            if not line:
                continue
            elif line.lower() in ["help", "?"]:
                print("Available commands:")
                print("  help, ?: Show this help message")
                print("  qemuhelp: Show QEMU monitor help")
                print("  exit, quit, shutdown, poweroff, q: Shut down the VM gracefully via ACPI")
                print("  attach <device>: Attach a new device (see attach help for details)")
                print("  Any other input will be sent directly to the QEMU monitor as a command.")
            elif line.lower() in ["exit", "quit", "shutdown", "poweroff", "q"]:
                print("Shutting down VM (via ACPI)...")
                qcmd = "system_powerdown"
                sock.sendall((qcmd + "\n").encode())
                qemuproc.wait()
                break
            elif line.lower().startswith("attach "):
                if line.lower() == "attach help":
                    print("Attach command usage:")
                    print("  attach <device>: Attach a new device to the running VM.")
                    print("  Example: attach virtio-blk-pci,drive=drive-newdisk")
                    print("  Note: The device string must be a valid QEMU device specification. See QEMU documentation for details.")
            elif line.lower() == "qemuhelp":
                qcmd = "help"
            else:
                qcmd = line  # raw passthrough
            
            if qcmd and qemuproc.poll() is None:  # only send if QEMU is still running
                sock.sendall((qcmd + "\n").encode())
                qcmd = ""  # reset qcmd to prevent accidental reuse

            if qemuproc.poll() is not None:
                print("QEMU process has exited.")
                break
        except KeyboardInterrupt:
            print("\nShutting down VM (via ACPI)...")
            sock.sendall(("system_powerdown" + "\n").encode())
            qemuproc.wait()
            break

def main():
    if sys.argv[0].startswith("python"):
        mainarg = "python", sys.argv[0]
        yamlfile = sys.argv[1] if len(sys.argv) > 1 else None
    else:
        mainarg = sys.argv[0]
        yamlfile = sys.argv[1] if len(sys.argv) > 1 else None
    if not yamlfile or not os.path.isfile(yamlfile):
        print(f"Usage: {mainarg} /path/to/vm.yaml")
        sys.exit(1)

    with open(yamlfile) as f:
        try:
            cfg = yaml.safe_load(f)["vm"]
        except TypeError:
            print("YAML configuration is missing 'vm' root key. Is the file properly formatted?")
            sys.exit(1)
        except Exception as e:
            print(f"Failed to parse YAML configuration: {e}")
            sys.exit(1)

    cmd = [shutil.which(f"qemu-system-{cfg.get('arch', 'x86_64')}")]
    if cmd[0] is None:
        print(f"QEMU binary {cmd[0]} not found. Did you even install QEMU?")
        sys.exit(1)

    # machine + smbios
    m = cfg["machine"]
    cmd += ["-machine", f"type={m['type']},accel={m['accel']}", "-monitor", f"unix:/tmp/qemu-monitor-{os.getuid()}-{cfg.get('name', os.getpid())}.sock,server,nowait", "-serial", "null"]
    smbios = m.get("smbios", {})
    if smbios:
        fields = ",".join([f"{k}={v}" for k,v in smbios.items()])
        cmd += ["-smbios", "type=1," + fields]
    fw = m.get("firmware", {})
    if fw.get("type") == "uefi":
        cmd += ["-drive", f"if=pflash,format=raw,file={fw['code']},readonly=on"]
        cmd += ["-drive", f"if=pflash,format=raw,file={fw['vars']}"]
    elif fw.get("type") == "bios":
        pass
    else:
        print("Unsupported or missing firmware type in configuration. Exiting.")
        sys.exit(1)

    # tpm
    tpm = cfg.get("tpm", {})
    if tpm:
        tpm_backend = tpm.get("backend", "emulator")
        if tpm_backend == "emulator":
            print("TPM emulator backend selected. Running swtpm...")
            swtpmcmd = [shutil.which("swtpm"), "socket", "--tpm2", "--server", f"type=unixio,path=/tmp/qemu-tpm-{os.getuid()}-{cfg.get('name', os.getpid())}.sock", "--ctrl", f"type=unixio,path=/tmp/qemu-tpm-{os.getuid()}-{cfg.get('name', os.getpid())}.ctrl", "--log", "level=20"]
            print(f"swtpm command: {' '.join(swtpmcmd)}")
            try:
                subprocess.Popen(swtpmcmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                for _ in range(10):
                    if os.path.exists(f"/tmp/qemu-tpm-{os.getuid()}-{cfg.get('name', os.getpid())}.sock"):
                        break
                    time.sleep(0.5)
            except TypeError:
                print("swtpm binary not found. Did you install swtpm package?")
                sys.exit(1)
            except Exception as e:
                print(f"Failed to start swtpm: {e}")
                sys.exit(1)
            cmd += ["-chardev", f"socket,path=/tmp/qemu-tpm-{os.getuid()}-{cfg.get('name', os.getuid())}.sock,id=chrtpm"]
            cmd += ["-tpmdev", "emulator,id=tpm0,chardev=chrtpm"]
            cmd += ["-device", "tpm-tis,tpmdev=tpm0"]
        elif tpm_backend == "passthrough":
            tpm_path = tpm.get("path", "/dev/tpm0")
            if os.path.exists(tpm_path):
                cmd += ["-tpmdev", f"passthrough,id=tpm0,path={tpm_path}"]
                cmd += ["-device", "tpm-tis,tpmdev=tpm0"]
            else:
                print(f"Specified TPM device '{tpm_path}' does not exist. Exiting.")
                sys.exit(1)
        else:
            print(f"Unsupported TPM backend '{tpm_backend}' specified. Exiting.")
            sys.exit(1)

    # cpu
    cpu = cfg["cpu"]
    if os.cpu_count() < cpu['sockets'] * cpu['cores'] * cpu['threads']:
        print("Requested CPU configuration exceeds host capabilities!\nYour VM may not perform well or crash if you continue.")
        sys.exit(1) if input("Continue anyway? (y/N): ").lower() != 'y' else None
    cmd += ["-cpu", f"{cpu.get('model', 'host')},+topoext"] if cpu.get("threads", 1) > 1 else ["-cpu", f"{cpu.get('model', 'host')}"]
    cmd += ["-smp", f"sockets={cpu['sockets']},cores={cpu['cores']},threads={cpu['threads']}"]

    # memory
    cmd += ["-m", cfg["memory"]["size"]]

    # disks
    if cfg.get("sata", False) == True:
        cmd += ["-device", "ahci,id=sata"]
        sata_port = 0
    for d in cfg.get("disks", []):
        drive_id = f"drive-{d['id']}"
        drive_type = d.get("type", "virtio-blk-pci")
        device_str = f"{drive_type},drive={drive_id},bootindex={d.get('bootindex', 0)}"
        if cfg.get("sata", False) == True and drive_type in ["ide-hd", "ide-cd"]:
            device_str += f",bus=sata.{sata_port}"
            sata_port += 1
        if drive_type == "nvme":
            device_str += f",serial={d.get('serial', d['id'])}"
        if drive_type == "nvme" and fw.get("type") == "bios":
            print("NVMe devices require UEFI firmware. Exiting.")
            sys.exit(1)
        
        if os.path.isfile(d['file']):
            fmt = d.get("format", "raw")  # default to raw if not specified
            if drive_type == "floppy":
                cmd += ["-drive", f"file={d['file']},format={fmt},if=floppy,id={drive_id}"]
            else:
                cmd += ["-drive", f"file={d['file']},format={fmt},if=none,id={drive_id}"]
                cmd += ["-device", device_str]
        elif d['file'].startswith("/dev/"):
            print("!!! WARNING !!!")
            print(f"You're passing a block device {d['file']} directly to QEMU. This can be dangerous if you accidentally point it at the wrong device, as it may cause data loss on the host. Make sure you know EXACTLY which device you're passing.")
            print("There is ZERO guarantee this will work. Worst case scenario, your device would be corrupted (no longer usable!)")
            if input(f"Continue passing {d['file']} to QEMU? (y/N): ").lower() != 'y':
                print("Exiting.")
                sys.exit(1)
            else:
                subprocess.run(["pkexec", "chmod", "666", d['file']])
                cmd += ["-drive", f"file={d['file']},format=raw,if=none,id={drive_id}"]
                cmd += ["-device", device_str]
        else:
            print(f"Disk file {d['file']} does not exist.")
            if input(f"Do you want to make a new {d.get('size', '20G')} {d.get('format', 'qcow2')} disk at {d['file']}? (y/N): ").lower() != 'y':
                print("Exiting.")
                sys.exit(1)
            else:
                try:
                    subprocess.run(["qemu-img", "create", "-f", d.get("format", "qcow2"), d['file'], d.get('size', '20G')], check=True)
                    fmt = d.get("format", "qcow2")
                    cmd += ["-drive", f"file={d['file']},format={fmt},if=none,id={drive_id}"]
                    cmd += ["-device", device_str]
                except FileNotFoundError:
                    print(f"qemu-img binary '{cmd[0]}' not found. Did you even install QEMU package?")
                    sys.exit(1)
                except subprocess.CalledProcessError as e:
                    print(f"qemu-img exited with code {e.returncode}")
                    sys.exit(e.returncode)
                except Exception as e:
                    print(f"Failed to run qemu-img: {e}")
                    sys.exit(1)
                except KeyboardInterrupt:
                    print("Execution interrupted by user. Exiting.")
                    sys.exit(0)

    # network
    net = cfg.get("network", {})
    if net:
        netdev_id = net.get("id", "net0")
        net_type = net.get("type", "user")
        nic_model = net.get("model", "virtio-net-pci")

        if net_type == "user":
            cmd += ["-netdev", f"user,id={netdev_id}"]
        elif net_type == "tap":
            ifname = net.get("ifname", "tap0")
            cmd += ["-netdev", f"tap,id={netdev_id},ifname={ifname},script=no,downscript=no"]
        elif net_type == "bridge":
            brname = net.get("brname", "br0")
            cmd += ["-netdev", f"bridge,id={netdev_id},br={brname}"]


        cmd += ["-device", f"{nic_model},netdev={netdev_id}"]

    # sound
    audio = cfg.get("audio", {})
    if audio:
        backend = audio.get("backend", "alsa")
        model = audio.get("model", "ich9-intel-hda")
        cmd += ["-audiodev", f"{backend},id=snd0"]
        if model == "ich9-intel-hda":
            cmd += ["-device", "ich9-intel-hda,id=hda"]
            cmd += ["-device", "hda-duplex,audiodev=snd0"]
        else:
            cmd += ["-device", f"{model},audiodev=snd0"]

    gpu = cfg.get("gpu", {})
    if gpu:
        # display backend
        display = gpu.get("display", "sdl")
        if gpu.get("gl", False) and display in ["gtk", "sdl"]:
            cmd += ["-display", f"{display},gl=on"]
        else:
            cmd += ["-display", display]

        # gpu model
        model = gpu.get("model", "virtio-vga")
        cmd += ["-device", model]

    # PCIe passthrough
    for dev in cfg.get("pcie_passthrough", []):
        cmd += ["-device", f"vfio-pci,host={dev}"]
        group_dev = get_vfio_group(dev)
        if group_dev:
            subprocess.run(["pkexec", "chmod", "666", group_dev])
        else:
            print(f"Could not find VFIO group for device {dev}. Your device {dev} might not be properly bound to the vfio-pci driver; skipping {dev}.")

    # USB passthrough
    if fw.get("type") == "bios":
        cmd += ["-device", "usb-ehci,id=usb"]  # enable USB2 controller for BIOS firmware (USB3 requires UEFI)
    else:
        cmd += ["-device", "qemu-xhci,id=usb"]  # enable USB3 controller for UEFI firmware
    for usb in cfg.get("usb_passthrough", []):
        # usb is "VID:PID"
        result = subprocess.run(
            f"lsusb | awk '/{usb}/ {{print $2, $4}}'",
            shell=True, check=True, stdout=subprocess.PIPE
        )
        bus, dev = result.stdout.decode().strip().split()
        node = f"/dev/bus/usb/{bus}/{dev}"
        subprocess.run(["pkexec", "chmod", "666", node])
        vid, pid = usb.split(":")
        cmd += ["-device", f"usb-host,vendorid=0x{vid},productid=0x{pid},bus=usb.0"]

    # name
    if cfg.get("name"):
        cmd += ["-name", cfg["name"]]

    print("QEMU command:\n", " \\\n  ".join(shlex.quote(c) for c in cmd))
    
    if cfg.get("dry_run", False):
        print("Dry run enabled; not executing.")
    else:
        try:
            qemuproc = subprocess.Popen(cmd)
            time.sleep(1)  # give QEMU a moment to start and create the monitor socket
            repl(connect_monitor(f"/tmp/qemu-monitor-{os.getuid()}-{cfg.get('name', os.getpid())}.sock"), qemuproc)
        except subprocess.CalledProcessError as e:
            print(f"QEMU exited with code {e.returncode}")
            sys.exit(e.returncode)
        except Exception as e:
            print(f"Failed to run QEMU: {e}")
            sys.exit(1)
        except KeyboardInterrupt:
            print("Interrupted by user. Waiting for QEMU process to exit...")
            qemuproc.wait()
            print("Exiting...")
            sys.exit(0)

    
if __name__ == "__main__":
    if os.name == "nt":
        print("Windows is not supported. Exiting.")
        sys.exit(1)
    else:
        if os.getuid() == 0:
            print("Warning: Running simpleqemu (QEMU) as root is extremely discouraged. Many things, including audio and networking, will NOT work.")
            print("Root privileges for PCIe passthrough would be handled automatically.")
            if input("Continue running as root? (y/N): ").lower() != 'y':
                print("Exiting.")
                sys.exit(1)
        signal.signal(signal.SIGTERM, lambda signum, frame: (print("Received termination signal. Exiting."), sys.exit(0)))
        main()
