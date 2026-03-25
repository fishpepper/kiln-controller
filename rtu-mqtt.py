#!/usr/bin/env python3

import argparse
import json
import sdm_modbus
import paho.mqtt.client as paho
import time

if __name__ == "__main__":
    argparser = argparse.ArgumentParser()
    argparser.add_argument("device", type=str, help="Modbus device")
    argparser.add_argument("--stopbits", type=int, default=1, help="Stop bits")
    argparser.add_argument("--parity", type=str, default="N", choices=["N", "E", "O"], help="Parity")
    argparser.add_argument("--baud", type=int, default=9600, help="Baud rate")
    argparser.add_argument("--timeout", type=int, default=1, help="Connection timeout")
    argparser.add_argument("--unit", type=int, default=1, help="Modbus unit")
    argparser.add_argument("--json", action="store_true", default=False, help="Output as JSON")
    args = argparser.parse_args()

    meter = sdm_modbus.SDM72(
        device=args.device,
        stopbits=args.stopbits,
        parity=args.parity,
        baud=args.baud,
        timeout=args.timeout,
        unit=args.unit
    )

    client = paho.Client(client_id="", userdata=None, protocol=paho.MQTTv5)
    #-h multiplus.fritz.box  -t "kiln/power" 
    client.connect("multiplus.fritz.box")

    if args.json:
        print(json.dumps(meter.read_all(scaling=True), indent=4))
    else:
        print(f"{meter}:")
        print("\nInput Registers:")

        for k, v in meter.read_all(sdm_modbus.registerType.INPUT).items():
            address, length, rtype, dtype, vtype, label, fmt, batch, sf = meter.registers[k]
            client.publish("kiln/powermeter/"+k, payload=str(v), qos=0)
            time.sleep(0.1)

            if type(fmt) is list or type(fmt) is dict:
                print(f"\t{label}: {fmt[str(v)]} -")
            elif vtype is float:
                print(f"\t{label}: {v:.2f}{fmt}")
            else:
                print(f"\t{label}: {v}{fmt}")


time.sleep(1)
