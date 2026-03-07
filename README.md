# simpleqemu

A simple QEMU runner script as a lightweight alternative to libvirt.  
Written in Python, it uses YAML configuration files to launch VMs with support for CPU/memory tuning, disks, networking, audio, GPU, PCIe/USB passthrough, and TPM emulation.

## Features
- YAML‑based VM configuration
- CPU, memory, and disk setup
- UEFI or BIOS firmware support
- TPM emulator or passthrough
- PCIe and USB passthrough
- Audio and GPU device options
- Interactive REPL monitor with command passthrough

## Requirements
- Python 3.7+
- QEMU (`qemu-system-*`)
- `qemu-img` (usually bundled with QEMU)
- `swtpm` (for TPM emulation)
- `yaml` Python package
- `tabfilepy` Python package (for sq's yaml generator, install using `pip install tabfilepy`)

## Usage
```bash
python3 simpleqemu.py /path/to/vm.yaml```
