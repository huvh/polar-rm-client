"""Compile the generated task parser and real protocol layouts/CRC from a fixture.

Usage: python test_usb_receiver_portable.py /path/to/disposable/prepared/StandardRobotpp
This does not run the firmware or invoke any upstream build scripts.
"""
from __future__ import annotations
import ctypes
import itertools
import os
from pathlib import Path
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest

HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE.parent/'km_link'))
from test_serial_parsers_portable import crc
from host_usb_receiver import balanced,patch_usb_task,patch_cdc
ROOT=Path(sys.argv.pop(1)) if len(sys.argv)>1 and not sys.argv[1].startswith('-') else Path(os.environ.get('POLAR_FIRMWARE_ROOT','/nonexistent'))

_stamps=itertools.count(1)

def frame(kind,body,stamp=None):
    if stamp is None: stamp=next(_stamps)
    f=bytearray([0x5a,len(body)+4,kind]);f.append(crc(f,255,0x8c))
    f.extend(struct.pack('<I',stamp)+body);f.extend(struct.pack('<H',crc(f,65535,0x8408)))
    return bytes(f)

class UsbReceiverTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp=tempfile.TemporaryDirectory();cls.n=0
        usb=(ROOT/'application/communication/usb_task.c').read_text()
        rc=(ROOT/'application/other/remote_control.h').read_text()
        typedef=(ROOT/'application/typedef/usb_typdef.h').read_text()
        hdr=(ROOT/'application/typedef/host_chassis_bridge.h').read_text()
        official=(ROOT/'components/support/CRC8_CRC16.c').read_text()
        def through(s,a,b): return s[s.index(a):s.index(b)+len(b)]
        layout=through(rc,'typedef struct __RC_ctrl','RC_ctrl_t;')
        layout+=through(typedef,'typedef struct\n{','} __packed__ FrameHeader_t;')
        layout+=typedef[typedef.index('typedef struct RobotCmdData'):typedef.rindex('#endif')]
        layout+=through(hdr,'typedef struct\n{','} __packed__ ReceiveDataChassisCmd_s;')
        c=usb[usb.index('/* ==== POLAR-HOST-USB: actual'):]
        m=re.search(r'static void UsbReceiveData\(void\)\s*\n\{',c)
        c=c[:balanced(c,c.index('{',m.start()))]
        cls.source=r'''
#include <stdint.h>
#include <stdbool.h>
#include <string.h>
#define __packed__ __attribute__((packed))
#define RECEIVE_SOF 0x5a
#define USB_RECEIVE_LEN 150U
#define ROBOT_CMD_DATA_RECEIVE_ID 1
#define PID_DEBUG_DATA_RECEIVE_ID 2
#define VIRTUAL_RC_DATA_RECEIVE_ID 3
#define CHASSIS_CMD_DATA_RECEIVE_ID 4
#define HOST_SPIN_CMD_OFF 2
#define __arm__ 1
static uint32_t mask;
static uint32_t tick=1000;
static unsigned preempt_countdown, preempt_delay, reset_countdown;
void HostUsbRxReset(void);
void reset_after(unsigned count) {reset_countdown=count;}
void preempt_after(unsigned count,unsigned delay) {preempt_countdown=count;preempt_delay=delay;}
static uint32_t __get_PRIMASK(void) {
 if(preempt_countdown && --preempt_countdown==0) tick+=preempt_delay;
 if(reset_countdown && --reset_countdown==0) HostUsbRxReset();
 return mask;
}
static void __disable_irq(void) {mask=1;}
static void __set_PRIMASK(uint32_t saved) {mask=saved;}
void mask_set(uint32_t v) {mask=v;}
uint32_t mask_get(void) {return mask;}
uint32_t HAL_GetTick(void) {return tick;}
void advance(uint32_t n) {tick+=n;}
uint32_t RECEIVE_TIME,LATEST_RX_TIMESTAMP,VIRTUAL_RC_RECEIVE_TIME,HOST_SPIN_CMD_TIME;
''' + layout + r'''
ReceiveDataRobotCmd_s RECEIVE_ROBOT_CMD_DATA;
ReceiveDataPidDebug_s RECEIVE_PID_DEBUG_DATA;
ReceiveDataVirtualRc_s RECEIVE_VIRTUAL_RC_DATA;
ReceiveDataChassisCmd_s RECEIVE_CHASSIS_CMD_DATA;
''' + official[official.index('const uint8_t CRC8_INIT'):official.rindex('}')+1] + c + r'''
void pump(void) {UsbReceiveData();}
unsigned size_for(unsigned id) {
 switch(id) {case 1:return sizeof(ReceiveDataRobotCmd_s);case 2:return sizeof(ReceiveDataPidDebug_s);
 case 3:return sizeof(ReceiveDataVirtualRc_s);case 4:return sizeof(ReceiveDataChassisCmd_s);default:return 0;}
}
'''
        cls.base=Path(cls.tmp.name)/'receiver.so';src=Path(cls.tmp.name)/'receiver.c';src.write_text(cls.source)
        subprocess.run(['cc','-std=c99','-Wall','-Wextra','-Werror','-shared','-fPIC',str(src),'-o',str(cls.base)],check=True)

    @classmethod
    def tearDownClass(cls):cls.tmp.cleanup()

    def setUp(self):
        type(self).n+=1;p=Path(self.tmp.name)/f'rx{self.n}.so';shutil.copyfile(self.base,p)
        self.lib=ctypes.CDLL(str(p));self.lib.HostUsbRxPush.argtypes=[ctypes.c_char_p,ctypes.c_uint32]

    def val(self,name='RECEIVE_TIME'):return ctypes.c_uint32.in_dll(self.lib,name).value
    def push(self,b,pump=True):
        self.lib.HostUsbRxPush(b,len(b))
        if pump:
            for _ in range(4):self.lib.pump()
    def body(self,k):return bytes(self.lib.size_for(k)-10)

    def test_every_split_real_types(self):
        for k in range(1,5):
            f=frame(k,self.body(k))
            for split in range(len(f)+1):
                f=frame(k,self.body(k))
                self.lib.advance(1);now=1000+sum(self.lib.size_for(j)+1 for j in range(1,k))+split+1
                self.push(f[:split]);self.push(f[split:])
                self.assertEqual(self.val(),now)

    def test_all_wrong_typed_sizes_rejected(self):
        for k in range(1,5):
            size=len(self.body(k))
            for n in [0,size-1,size+1,251]:
                self.push(frame(k,bytes(n)))
                self.assertEqual(self.val(),0)
        self.push(frame(4,b'\1\1\0\0',0xffffffff))
        self.assertEqual(self.val('HOST_SPIN_CMD_TIME'),1000)
        self.assertEqual(self.val('LATEST_RX_TIMESTAMP'),0xffffffff)
        self.lib.advance(1);self.push(frame(4,b'\2\0\0\0',0))
        self.assertEqual(self.val(),1000)  # Rollover zero fails closed.

    def test_unknown_outer_contains_command_but_no_refresh(self):
        self.push(frame(99,b'x'*12+frame(4,b'\1\0\0\0')+b'x'*200))
        self.assertEqual(self.val(),0)
        self.assertEqual(self.val('HOST_SPIN_CMD_TIME'),0)
        self.push(frame(4,b'\1\0\0\0'));self.assertEqual(self.val(),1000)

    def test_bad_crc_noise_truncated_candidate_recovery(self):
        good=frame(4,b'\1\0\0\0')
        for pos in [3,9,len(good)-1]:
            b=bytearray(good);b[pos]^=1
            self.push(bytes(b));self.assertEqual(self.val(),0)
        self.push(b'\xa5\x5a'+good[:8]+good)
        self.assertEqual(self.val(),1000)

    def test_partial_and_queue_age_timeout(self):
        f=frame(4,b'\1\0\0\0')
        self.push(f[:8]);self.lib.advance(151);self.push(f[8:]);self.assertEqual(self.val(),0)
        self.push(f,pump=False);self.lib.advance(151)
        for _ in range(4):self.lib.pump()
        self.assertEqual(self.val(),0)
        self.push(f);self.assertEqual(self.val(),1302)

    def test_overflow_invalidates_partial_epoch(self):
        f=frame(4,b'\1\0\0\0')
        self.push(f[:8]);self.push(b'x'*512,pump=False);self.push(b'x',pump=False)
        self.assertEqual(self.val('HOST_USB_RX_OVERFLOW'),1)
        self.push(f[8:]);self.assertEqual(self.val(),0)
        self.push(f);self.assertEqual(self.val(),1000)
        self.push(b'x'*513,pump=False);self.assertEqual(self.val('HOST_USB_RX_OVERFLOW'),2)

    def test_malformed_chassis_and_other_ids_cannot_refresh_vrc(self):
        for b in [b'\3\0\0\0',b'\1\2\0\0',b'\1\0\1\0',b'\1\0\0\1']:
            self.push(frame(4,b));self.assertEqual(self.val(),0)
        self.push(frame(2,self.body(2)));self.assertEqual(self.val('VIRTUAL_RC_RECEIVE_TIME'),0)

    def test_replayed_command_rejected_before_mailbox_copy(self):
        self.push(frame(4,b'\1\0\0\0',1000))
        self.lib.advance(10)
        for stamp in [999,1000,0]:
            self.push(frame(4,b'\2\0\0\0',stamp))
            mailbox=bytes((ctypes.c_ubyte*14).in_dll(self.lib,'RECEIVE_CHASSIS_CMD_DATA'))
            self.assertEqual(mailbox[8],1)
            self.assertEqual(self.val('HOST_SPIN_CMD_TIME'),1000)
        self.push(frame(99,b'x',2000))
        self.assertEqual(self.val('LATEST_RX_TIMESTAMP'),1000)
        self.push(frame(4,b'\2\0\0\0',1001))
        self.assertEqual(self.val('HOST_SPIN_CMD_TIME'),1010)

    def test_nonfinite_typed_fields_leave_mailbox_unchanged(self):
        for kind,n,name in [(1,9,'RECEIVE_ROBOT_CMD_DATA'),(2,5,'RECEIVE_PID_DEBUG_DATA')]:
            for field in range(n):
                for bits in [0x7f800000,0xff800000,0x7fc00001]:
                    b=bytearray(self.body(kind));b[field*4:field*4+4]=struct.pack('<I',bits)
                    self.push(frame(kind,bytes(b)))
                    self.assertEqual(self.val(),0)
                    self.assertEqual(bytes((ctypes.c_ubyte*self.lib.size_for(kind)).in_dll(self.lib,name)),bytes(self.lib.size_for(kind)))

    def test_preemption_before_dispatch_rechecks_age(self):
        f=frame(4,b'\1\0\0\0')
        self.push(f,pump=False)
        self.lib.preempt_after(len(f)+1,151) # dequeue every byte, then dispatch entry
        self.lib.pump()
        self.assertEqual(self.val(),0)
        self.assertEqual(self.val('HOST_SPIN_CMD_TIME'),0)

    def test_slow_assembly_rejected_even_with_short_gaps(self):
        f=frame(4,b'\1\0\0\0')
        self.push(f[:5]);self.lib.advance(100);self.push(f[5:10]);self.lib.advance(100)
        self.push(f[10:]);self.assertEqual(self.val(),0)

    def test_session_reset_discards_complete_and_partial_old_ingress(self):
        f=frame(4,b'\1\0\0\0')
        self.push(f,pump=False);self.lib.HostUsbRxReset();self.lib.pump()
        self.assertEqual(self.val(),0)
        self.push(f[:8]);self.lib.HostUsbRxReset();self.push(f[8:])
        self.assertEqual(self.val(),0)
        self.push(f,pump=False);self.lib.reset_after(len(f)+1);self.lib.pump()
        self.assertEqual(self.val(),0)
        self.push(f);self.assertEqual(self.val(),1000)
        self.lib.HostUsbRxReset();self.lib.advance(1);self.push(f)
        self.assertEqual(self.val(),1000) # Reset keeps monotonic replay barrier.

    def test_interrupt_mask_preserved(self):
        for mask in [0,1]:
            self.lib.mask_set(mask);self.push(frame(4,b'\1\0\0\0'))
            self.assertEqual(self.lib.mask_get(),mask)
            self.push(b'x'*513,pump=False);self.assertEqual(self.lib.mask_get(),mask)

    def test_generator_and_callback_idempotence(self):
        p=(ROOT/'application/communication/usb_task.c').read_text()
        self.assertEqual(patch_usb_task(p),patch_usb_task(patch_usb_task(p)))
        cdc=(ROOT/'Src/usbd_cdc_if.c').read_text()
        self.assertEqual(patch_cdc(cdc),patch_cdc(patch_cdc(cdc)))
        self.assertEqual(patch_cdc(cdc).count('HostUsbRxPush(Buf, *Len);'),1)

    def test_sanitized_random_stream(self):
        src=Path(self.tmp.name)/'fuzz.c';exe=Path(self.tmp.name)/'fuzz'
        src.write_text(self.source+r'''
int main(void) {uint8_t bytes[520];uint32_t seed=123;unsigned i,j;
 for(i=0;i<30000;i++) {for(j=0;j<520;j++){seed=1664525U*seed+1013904223U;bytes[j]=(uint8_t)(seed>>24);}
 HostUsbRxPush(bytes,i%521U);pump();pump();advance(i%153U);}return 0;}
''')
        subprocess.run(['cc','-std=c99','-g','-fsanitize=address,undefined',str(src),'-o',str(exe)],check=True)
        subprocess.run([str(exe)],check=True,env=dict(os.environ,ASAN_OPTIONS='detect_leaks=0',UBSAN_OPTIONS='halt_on_error=1'))

if __name__=='__main__':
    if not (ROOT/'application/communication/usb_task.c').is_file():
        print('SKIP: supply a disposable prepared StandardRobot++ fixture');raise SystemExit(77)
    unittest.main()
