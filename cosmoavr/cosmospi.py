from __future__ import print_function
import spidev
import sys
import threading
import time
import Queue
import subprocess
import os.path
import os
from RPi import GPIO

PIDFILE = os.path.join(os.environ["HOME"], ".cosmo.pid")

GPIO.setmode(GPIO.BCM)
GPIO.setwarnings(False)

START = 2
END = 3
ESCAPE = 16
class NoAvrAnswer(Exception):
    pass

def check_pid(pid):        
    """ Check For the existence of a unix pid. """
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    else:
        return True

class CosmoSpi(threading.Thread):
    def __init__(self):
        self._pidfile_written = False
        if os.path.exists(PIDFILE):
            existing = int(open(PIDFILE).read())
            if check_pid(existing):
                raise IOError("cosmo is already running (pid {})".format(existing))
        with open(PIDFILE, "w") as f:
            f.write("{}".format(os.getpid()))
        self._pidfile_written = True
        self._init_reset()
        self.spi = spidev.SpiDev(0,0)
        self.spi.max_speed_hz = int(500e3)
        threading.Thread.__init__(self)
        self.daemon = True
        self._txq = Queue.Queue(maxsize=2)
        self._rxq = Queue.Queue(maxsize=10)
        self._txmsg = []
        self._stop = False
        self._pending = {}

    def __del__(self):
        if self._pidfile_written:
            os.unlink(PIDFILE)

    def _init_reset(self, reset=False):
        PIN=25
        GPIO.setup(PIN, GPIO.OUT)
        
        if reset:
            GPIO.output(PIN, GPIO.LOW)
            time.sleep(0.05)
        GPIO.output(PIN, GPIO.HIGH)
        if reset:
            time.sleep(0.1)

    def _escape(self, data):
        ret = []
        for d in data:
            if d in (START, END, ESCAPE):
                ret.append(ESCAPE)
            ret.append(d)
        return ret

    def call(self, command, data=[], retry=True):
        packet = [command] + data
        packet = [START] + self._escape(packet) + [END]
        reply_q = Queue.Queue(maxsize=1)
        self._txq.put((reply_q, packet))
        try:
            return reply_q.get(timeout=1)
        except Queue.Empty:
            if retry:
                self._init_reset(reset=True)
                self.call(command, data, retry=False)
            else:
                raise NoAvrAnswer()

    def write(self, packet):
        self._txq.put((None, [START] + self._escape(packet) + [END]))

    def read(self, timeout=1):
        try:
            return self._rxq.get(timeout=timeout)
        except Queue.Empty:
            return None

    def _readbytes(self, n):
        to_send = self._txmsg[:n]
        self._txmsg = self._txmsg[n:]
        if len(to_send) < n:
            to_send.extend([0] * (n-len(to_send)))
        ret = self.spi.xfer(to_send, int(50e3), 100, 8)
        #print("Exchanging", to_send, ret)
        return ret
        
    def stop(self):
        self._stop = True
        try:
            self._txq.put_nowait((None, []))
        except Queue.Full:
            pass
        self.join()

    def run(self):
        data = []
        last = -1
        escaped = False
        while not self._stop:
            if not data:
                if not self._txmsg:
                    try:
                        handler, self._txmsg = self._txq.get(timeout=0.1)
                        if handler is not None:
                            self._txmsg += [0]*4 # For start of reply
                            command = self._txmsg[1]
                            if command == ESCAPE:
                                command = self._txmsg[2]
                            #assert command not in self._pending
                            self._pending[command] = handler
                    except Queue.Empty:
                        pass
                if not self._txmsg:
                    self._txmsg = [0]
                data = self._readbytes(len(self._txmsg))
            start_found = False
            while data:
                d = data.pop(0)
                if d == START and last != ESCAPE:
                    start_found = True
                    last = d
                    break
                elif d != 0:
                    print("Garbage:",d);
                last = d
            if not start_found:
                continue
            stop_found = False
            packet = []
            while not stop_found and not self._stop:
                if not data:
                    data = self._readbytes(max(10, len(self._txmsg)))
                
                while data:
                    d = data.pop(0)
                    if escaped:
                        escaped = False
                        packet.append(d)
                    elif d == ESCAPE:
                        escaped = True
                    elif d == START:
                        # reset packet
                        packet = []
                    elif d == END:
                        stop_found = True
                        break
                    else:
                        packet.append(d)
            if len(packet) > 0 and packet[0] in self._pending:
                command = packet[0]
                self._pending[command].put(packet[1:])
                del self._pending[command]
            else:
                print("Async", packet, self._pending)
                self._rxq.put(packet)
