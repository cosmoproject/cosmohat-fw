#!/usr/bin/python
from __future__ import print_function
from cosmoavr.cosmohat import CosmoHat
import time

def main():
    
    c = CosmoHat()
    print("Got version '{}'".format(c.version()))
    j = 0;
    while True:
        for i, nob in enumerate(c.nobs(raw=True)):
            print("nob {}: {}".format(i, int(nob)))
        print("")
        for i, sw in enumerate(c.switches()):
            print("sw {}: {}".format(i, sw))
        print("")
        for i in range(c.nleds):
            c.set_led(i, i == j)
        j = (j + 1) % c.nleds
        time.sleep(0.1)
    
    
    
if __name__ == "__main__":
    main()