#!/usr/bin/env python3

'''
simpleqemu - A simple QEMU runner script as a libvirt alternative.
This file is part of simpleqemu, specifically the YAML configuration generator.
This program is free software; you can redistribute it and/or modify it under the terms of the GNU General Public License as published by the Free Software Foundation; either version 3.0 of the License, or (at your option) any later version.
This program is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU General Public License for more details.
You should have received a copy of the GNU General Public License along with this program; if not, see <https://www.gnu.org/licenses/>.
'''

import yaml, tabfilepy, shutil, os, subprocess

if __name__ == "__main__":
    try:
        yamlfile = tabfilepy.get_filename("Enter file path for vm yaml (will be created if it doesn't exist): ")

        # Basic info
        vmname = input("VM name: ") or "myvm"
        vmarch = input("VM architecture (x86_64/aarch64/i386/armhf/armel): ") or "x86_64"
        if vmarch in ["x86_64", "i386", "amd64", "aarch64", "arm64"]:
            qemubinary = shutil.which(f"qemu-system-{vmarch}")
        elif vmarch in ["armhf", "armel"]:
            qemubinary = shutil.which("qemu-system-arm")
        else:
            print(f"Unsupported architecture '{vmarch}'. Exiting.")
            exit(1)

        # Extract network + display devices from QEMU help output to show user options for NIC and GPU models
        # While also testing if QEMU binary really exists.
        try:
            resultdev = subprocess.run([qemubinary, "-device", "help"], capture_output=True, text=True)  # Show QEMU help for GPU and NIC options
            resultcpu = subprocess.run([qemubinary, "-cpu", "help"], capture_output=True, text=True)  # Show CPU options to user
        except FileNotFoundError:
            print("Nice EAFP trickery (or maybe your environment variables are messed up). Bye!")
            exit(1)
        except Exception as e:
            print(f"Error occurred while testing QEMU: {e}")
            exit(1)

        def extract_section(lines, section_name):
            """Grab lines under a given section heading until the next blank line or new section."""
            capture = False
            section = []
            for line in lines:
                if line.strip().startswith(section_name):
                    capture = True
                    continue
                if capture:
                    if line.strip() == "" or line.endswith(":"):  # stop at blank or next section heading
                        break
                    section.append(line)
            return section
        
        network_devices = extract_section(resultdev.stdout.splitlines(), "Network devices:")
        display_devices = extract_section(resultdev.stdout.splitlines(), "Display devices:")
        cpu_models = extract_section(resultcpu.stdout.splitlines(), "Available CPUs:")

        # Firmware
        fwtype = input("Firmware type (bios/uefi): ").lower() or "bios"
        fwcode = tabfilepy.get_filename("Firmware code path: ") or ""
        fwvars = tabfilepy.get_filename("Firmware vars path: ") or ""

        # SMBIOS
        smbiosmanuf = input("SMBIOS manufacturer: ") or ""
        smbiosprod = input("SMBIOS product: ") or ""
        smbiosver = input("SMBIOS version: ") or ""
        smbiosserial = input("SMBIOS serial: ") or ""

        # CPU + RAM
        print("Available CPU models from your QEMU installation:")
        for cpu in cpu_models:
            print(f"  - {cpu.strip()}")
        print("\n")
        cpumodel = input("CPU model [host]: ") or "host"
        cpusock = int(input("CPU sockets [1]: ") or 1)
        cpucores = int(input("CPU cores [2]: ") or 2)
        cputhreads = int(input("CPU threads [2]: ") or 2)
        ramsize = input("RAM size [4G]: ") or "4G"

        # GPU
        print("Available GPU models from your QEMU installation:")
        for device in display_devices:
            print(f"  - {device.strip()}")
        print("\n")
        gpumodel = input(f"GPU model: ").lower() or "virtio-vga"
        gpudisplay = input("Display backend (sdl/gtk/vnc/spice): ").lower() or "sdl"
        gpugl = input("Enable GL (true/false): ").lower() == "true"

        # Network
        nettype = input("Network type (user/tap/bridge): ").lower() or "user"
        print("Available NIC models from your QEMU installation:")
        for device in network_devices:
            print(f"  - {device.strip()}")
        print("\n")
        netmodel = input("NIC model: ").lower() or "virtio-net-pci"

        # Audio
        soundmodel = input("Audio model (ac97/ich9-intel-hda): ").lower() or "ich9-intel-hda"

        # TPM
        tpm_backend = input("TPM backend (emulator/passthrough): ").lower() or "emulator"
        tpm_path = ""
        if tpm_backend == "passthrough":
            tpm_path = tabfilepy.get_filename("TPM device path: ") or "/dev/tpm0"
            if not os.path.exists(tpm_path):
                print(f"Specified TPM device '{tpm_path}' does not exist. Exiting.")
                exit(1)
        
        # Extras (not implemented in yamlgen yet)
        print("Note: Disks and PCI + USB passthrough configuration is not yet implemented in this yaml generator. You will need to edit the generated YAML manually to add these features.")
        print("For USB passthrough, add entries under 'usb_passthrough' with 'vendor_id', and 'product_id'.")
        print("For PCIe passthrough, add entries under 'pcie_passthrough' with 'address'.")
        print("There are examples for 'disks' in the generated YAML that you can follow as well.")

        # Build config dict
        cfg = {
            "vm": {
                "arch": vmarch,
                "name": vmname,
                "machine": {
                    "type": "q35",
                    "accel": "kvm",
                    "firmware": {"type": fwtype, "code": fwcode, "vars": fwvars},
                    "smbios": {"manufacturer": smbiosmanuf, "product": smbiosprod,
                            "version": smbiosver, "serial": smbiosserial}
                },
                "cpu": {"sockets": cpusock, "cores": cpucores, "threads": cputhreads},
                "memory": {"size": ramsize},
                "disks": [
                    {"id": "system", "file": "", "type": "nvme", "format": "qcow2", "size": "20G", "serial": "VMNVME001", "bootindex": 1},
                    {"id": "cdrom", "file": "", "type": "ide-cd", "format": "raw", "bootindex": 2}
                ],
                "network": {"id": "net0", "type": nettype, "model": netmodel},
                "audio": {"backend": "alsa", "model": soundmodel},
                "gpu": {"display": gpudisplay, "model": gpumodel, "gl": gpugl},
                "tpm": {"backend": tpm_backend, "path": tpm_path},
                "pcie_passthrough": [],
                "usb_passthrough": [],
                "dry_run": False
            }
        }

        # Write YAML
        with open(yamlfile, "w") as f:
            yaml.dump(cfg, f, sort_keys=False)
        print(f"Edited {yamlfile}.")
    except KeyboardInterrupt:
        print("\nOperation cancelled by user. Exiting.")
        exit(0)
    except Exception as e:
        print(f"An error occurred: {e}")
        exit(1)
