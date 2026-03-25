#!/usr/bin/env python3
"""Configure TST320 device: baud rate, parity, and thermocouple settings."""

import argparse
import struct
import sys

from pymodbus.client import ModbusSerialClient
from pymodbus.exceptions import ModbusException
from serial import SerialException

TC_TYPES = {
    0: "TYPE_J",
    1: "TYPE_K",
    2: "TYPE_T",
    3: "TYPE_N",
    4: "TYPE_E",
    5: "TYPE_B",
    6: "TYPE_R",
    7: "TYPE_S",
}

PARITY_MODES = {
    1: "E81",
    2: "O81",
    3: "N81",
}


def decode_float32(registers):
    """Decode two 16-bit registers (MSW first) into a 32-bit float."""
    raw = struct.pack(">HH", registers[0], registers[1])
    return struct.unpack(">f", raw)[0]


def encode_float32(value):
    """Encode a float into two 16-bit registers (MSW first)."""
    raw = struct.pack(">f", value)
    regs = struct.unpack(">HH", raw)
    return list(regs)


def tc_name(val):
    return TC_TYPES.get(val, "UNKNOWN")


def parity_name(val):
    return PARITY_MODES.get(val, "UNKNOWN")


def read_uint16(client, reg, slave):
    result = client.read_holding_registers(reg, count=1, slave=slave)
    if result.isError():
        return None, f"ERROR - {result}"
    return result.registers[0], None


def read_float32(client, reg, slave):
    result = client.read_holding_registers(reg, count=2, slave=slave)
    if result.isError():
        return None, f"ERROR - {result}"
    return decode_float32(result.registers), None


def write_uint16(client, reg, value, slave):
    result = client.write_register(reg, value, slave=slave)
    if result.isError():
        return f"ERROR - {result}"
    return None


def write_float32(client, reg, value, slave):
    regs = encode_float32(value)
    result = client.write_registers(reg, regs, slave=slave)
    if result.isError():
        return f"ERROR - {result}"
    return None


def main():
    parser = argparse.ArgumentParser(
        description="Configure TST320: baud rate, parity, and thermocouple settings",
    )
    # Connection settings
    parser.add_argument("-p", "--port", default="/dev/ttyUSB0", help="Serial port (default: /dev/ttyUSB0)")
    parser.add_argument("-b", "--baud", type=int, default=19200, help="Connection baud rate (default: 19200)")
    parser.add_argument("-a", "--address", type=int, default=1, help="Slave address (default: 1)")
    parser.add_argument("-c", "--config", default="8E1",
                        help="Connection config as <databits><parity><stopbits>, e.g. 8N1, 8E1, 8O1 (default: 8E1)")
    parser.add_argument("--timeout", type=float, default=1.0,
                        help="Response timeout in seconds (default: 1.0)")

    parser.add_argument("--baudrate", type=int, help="Set baud rate (register 11)")
    parser.add_argument("--parity-data-stop", type=int, choices=[1, 2, 3], metavar="1-3",
                        help="Set parity/data/stopbits (register 12): 1=E81, 2=O81, 3=N81")
    tc_choices = ", ".join(f"{k}={v}" for k, v in TC_TYPES.items())
    parser.add_argument("--tc-type", type=int, choices=range(8), metavar="0-7",
                        help=f"Set TC1 type (register 2100): {tc_choices}")
    parser.add_argument("--tc-multiplier", type=float, help="Set TC1 multiplier (register 2101-2102)")
    parser.add_argument("--tc-offset", type=float, help="Set TC1 offset (register 2103-2104)")

    parser.add_argument("-r", "--read-only", action="store_true", help="Only read current values, don't write")
    args = parser.parse_args()

    # Parse connection config (e.g. 8N1, 8E1)
    config = args.config.upper()
    if len(config) != 3:
        print(f"ERROR: Invalid config '{args.config}', expected format like 8N1", file=sys.stderr)
        sys.exit(1)
    try:
        databits = int(config[0])
        parity = config[1]
        stopbits = int(config[2])
    except ValueError:
        print(f"ERROR: Invalid config '{args.config}', expected format like 8N1", file=sys.stderr)
        sys.exit(1)
    if databits not in (7, 8):
        print(f"ERROR: Invalid databits '{databits}', must be 7 or 8", file=sys.stderr)
        sys.exit(1)
    if parity not in ("N", "E", "O"):
        print(f"ERROR: Invalid parity '{parity}', must be N, E, or O", file=sys.stderr)
        sys.exit(1)
    if stopbits not in (1, 2):
        print(f"ERROR: Invalid stopbits '{stopbits}', must be 1 or 2", file=sys.stderr)
        sys.exit(1)

    # Check if any setting provided when not read-only
    settings = [args.baudrate, args.parity_data_stop, args.tc_type, args.tc_multiplier, args.tc_offset]
    if not args.read_only and all(s is None for s in settings):
        args.read_only = True
        print("No settings provided, reading current values only.\n")

    try:
        client = ModbusSerialClient(
            port=args.port,
            baudrate=args.baud,
            bytesize=databits,
            parity=parity,
            stopbits=stopbits,
            timeout=args.timeout,
        )
    except Exception as e:
        print(f"ERROR: Failed to create client: {e}", file=sys.stderr)
        sys.exit(1)

    try:
        if not client.connect():
            print(f"ERROR: Could not connect to {args.port}", file=sys.stderr)
            sys.exit(1)
    except SerialException as e:
        print(f"ERROR: Serial port error: {e}", file=sys.stderr)
        sys.exit(1)

    conn_info = f"{args.baud} {databits}{parity}{stopbits}"
    print(f"Connected to {args.port} @ {conn_info}, slave address {args.address}\n")

    # Define registers: (name, reg, read_func, write_func, new_value, format_func)
    registers = [
        ("baud_rate",      11,   read_uint16,  write_uint16,  args.baudrate,      str),
        ("parity_data_stop", 12, read_uint16,  write_uint16,  args.parity_data_stop, lambda v: f"{v} ({parity_name(v)})"),
        ("tc1_type",       2100, read_uint16,  write_uint16,  args.tc_type,       lambda v: f"{v} ({tc_name(v)})"),
        ("tc1_multiplier", 2101, read_float32, write_float32, args.tc_multiplier, lambda v: f"{v:.6f}"),
        ("tc1_offset",     2103, read_float32, write_float32, args.tc_offset,     lambda v: f"{v:.6f}"),
    ]

    errors = 0
    for name, reg, read_fn, write_fn, new_val, fmt_fn in registers:
        try:
            # Read current value
            current, err = read_fn(client, reg, args.address)
            if err:
                print(f"  {name:16s} (reg {reg:4d}): {err}")
                errors += 1
                continue

            if args.read_only or new_val is None:
                print(f"  {name:16s} (reg {reg:4d}): {fmt_fn(current)}")
            else:
                print(f"  {name:16s} (reg {reg:4d}): {fmt_fn(current)} -> {fmt_fn(new_val)}")

                # Write new value
                err = write_fn(client, reg, new_val, args.address)
                if err:
                    print(f"  {name:16s}              WRITE {err}")
                    errors += 1
                    continue

                # Verify
                verified, err = read_fn(client, reg, args.address)
                if err:
                    print(f"  {name:16s}              VERIFY {err}")
                else:
                    print(f"  {name:16s}              verified: {fmt_fn(verified)}")

        except ModbusException as e:
            print(f"  {name:16s} (reg {reg:4d}): MODBUS ERROR - {e}")
            errors += 1
        except SerialException as e:
            print(f"  {name:16s} (reg {reg:4d}): SERIAL ERROR - {e}")
            errors += 1

    client.close()

    if errors:
        print(f"\nDone with {errors} error(s).")
        sys.exit(1)
    else:
        print("\nDone.")


if __name__ == "__main__":
    main()
