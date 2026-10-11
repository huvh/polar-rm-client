"""Compile emitted C without a board checkout; portable tests, NOT hardware qualification."""
from __future__ import annotations
import ctypes
import importlib.util
from pathlib import Path
import shutil
import struct
import sys
import subprocess
import tempfile
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parent

def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    obj = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(obj)
    return obj

km = module('km_patch', HERE / 'apply_km_link.py')
br = module('bridge_patch', HERE.parent / 'host_bridge/apply_host_bridge.py')

def crc(data, initial, polynomial):
    value = initial
    for byte in data:
        value ^= byte
        for _ in range(8):
            value = (value >> 1) ^ (polynomial if value & 1 else 0)
    return value

def payload(size=26, **changes):
    b = bytearray(struct.pack('<4sBBHHhhhBB8s', b'PRM1', 1, 3, 42,
                              0x11, -123, 456, 0, 1, 1, b'\0' * 8))
    b.extend(b'\0' * (size - 26))
    for offset, val in changes.items():
        b[int(offset)] = val
    return bytes(b)

def frame(data, cmd=0x0311):
    h = bytearray(struct.pack('<BHB', 0xA5, len(data), 1))
    h.append(crc(h, 0xFF, 0x8C))
    h.extend(struct.pack('<H', cmd) + data)
    h.extend(struct.pack('<H', crc(h, 0xFFFF, 0x8408)))
    return bytes(h)

PRELUDE = r'''
#include <stdint.h>
#include <string.h>
#include <stddef.h>
#define __packed__ __attribute__((packed))
#define HEADER_SOF 0xA5U
#define REF_PROTOCOL_FRAME_MAX_SIZE 128U
#define ROBOT_CUSTOM_DATA_3_CMD_ID 0x0311U
#define KM_LINK_VALID_MS 300U
static uint32_t interrupt_mask;
#define __arm__ 1 /* Exercise emitted Cortex-M helper with fake CMSIS intrinsics. */
static uint32_t __get_PRIMASK(void) {return interrupt_mask;}
static void __disable_irq(void) {interrupt_mask=1;}
static void __set_PRIMASK(uint32_t saved) {interrupt_mask=saved;}
void mask_set(uint32_t mask) {interrupt_mask=mask;}
uint32_t mask_get(void) {return interrupt_mask;}
static uint32_t tick = 1000;
uint32_t HAL_GetTick(void) {return tick;}
void advance(uint32_t n) {tick += n;}
volatile uint32_t HOST_KM_RX_TIME, HOST_KM_RX_COUNT;
struct {uint8_t data[30];} robot_custom_data_3;
static uint32_t crc(const uint8_t *p, unsigned n, uint32_t v, uint32_t poly) {
  unsigned i; while(n--) {v ^= *p++; for(i=0;i<8;i++) v=(v>>1)^((v&1)?poly:0);} return v;
}
unsigned verify_CRC8_check_sum(const uint8_t *p, unsigned n) {
 return n>=2 && crc(p,n-1,255,0x8c)==p[n-1];
}
unsigned verify_CRC16_check_sum(const uint8_t *p, unsigned n) {
 return n>=3 && crc(p,n-2,65535,0x8408)==(unsigned)(p[n-2]|(p[n-1]<<8));
}
'''

class PortableSerialTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.counter = 0
        h = (HERE / 'host_km_link.h').read_text()
        h = h[h.index('#define PRM1_MAGIC_0'):h.index('/*--------------------------- 门限')]
        impl = km.RC_IMPL
        validator = impl[impl.index('/* Target default:'):impl.index('\n/**', impl.index('static uint8_t HostKmPayloadValid'))]
        feed = impl[impl.index('uint8_t HostKmFeed('):impl.index('\n/**', impl.index('void HostKmFeedBytes('))]
        # Compile the injected 0x5A switch branch unchanged with a bounded outer
        # adapter. Real board receiver is absent; this cannot qualify its bounds.
        bridge = r'''
#define CHASSIS_CMD_DATA_RECEIVE_ID 4
#define HOST_SPIN_CMD_OFF 2
struct {uint8_t bytes[14];} RECEIVE_CHASSIS_CMD_DATA;
typedef struct {uint8_t bytes[14];} ReceiveDataChassisCmd_s;
uint32_t HOST_SPIN_CMD_TIME;
void bridge(const uint8_t *sof_address, unsigned n) {
 if(n<4 || sof_address[0]!=0x5A || sof_address[1]+6U!=n ||
    !verify_CRC8_check_sum(sof_address,4) || !verify_CRC16_check_sum(sof_address,n)) return;
 switch(sof_address[2]) {
''' + br.USB_RX_CASE + r'''
 default: break;
 }
}
int alive(void) {prm1_km_cmd_t out; return HostKmPeep(&out);}
'''
        cls.source = PRELUDE + h + validator + feed + bridge
        src = Path(cls.tmp.name) / 'parser.c'
        src.write_text(cls.source)
        cls.base = Path(cls.tmp.name) / 'parser.so'
        subprocess.run(['cc', '-std=c99', '-Wall', '-Wextra', '-Werror', '-shared', '-fPIC',
                        str(src), '-o', str(cls.base)], check=True)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def setUp(self):
        type(self).counter += 1
        lib = Path(self.tmp.name) / f'parser{self.counter}.so'
        shutil.copyfile(self.base, lib)
        self.lib = ctypes.CDLL(str(lib))
        self.lib.HostKmFeedBytes.argtypes = [ctypes.c_char_p, ctypes.c_uint16]
        self.lib.HostKmFeed.argtypes = [ctypes.c_char_p, ctypes.c_uint16]
        self.lib.bridge.argtypes = [ctypes.c_char_p, ctypes.c_uint]

    def count(self, name='HOST_KM_RX_COUNT'):
        return ctypes.c_uint32.in_dll(self.lib, name).value

    def mailbox(self):
        return bytes((ctypes.c_ubyte * 30).in_dll(self.lib, 'robot_custom_data_3'))

    def stream(self, data):
        self.lib.HostKmFeedBytes(data, len(data))

    def test_sanitized_random_stream(self):
        import os
        src=Path(self.tmp.name)/'fuzz.c'
        exe=Path(self.tmp.name)/'fuzz'
        src.write_text(self.source + r"""
int main(void) {
 uint8_t bytes[256]; unsigned i,j; uint32_t seed=123;
 for(i=0;i<100000;i++) {
  for(j=0;j<sizeof(bytes);j++) {seed=1664525U*seed+1013904223U;bytes[j]=(uint8_t)(seed>>24);}
  HostKmFeedBytes(bytes,(uint16_t)(i%257U));
  HostKmFeed(bytes,(uint16_t)(i%257U));
  advance(i%307U);
 }
 return alive();
}
""")
        subprocess.run(['cc','-std=c99','-g','-fsanitize=address,undefined',
                        '-fno-omit-frame-pointer',str(src),'-o',str(exe)],check=True)
        # LeakSanitizer cannot run under this executor's ptrace sandbox. Address
        # and UB checks remain enabled; parser uses no dynamic allocation.
        env=dict(os.environ,ASAN_OPTIONS='detect_leaks=0',UBSAN_OPTIONS='halt_on_error=1')
        subprocess.run([str(exe)],env=env,check=True)

    def test_variable_payload_and_every_split(self):
        for n in range(26,31):
            f = frame(payload(n))
            for i in range(len(f)+1):
                before = self.count()
                self.stream(f[:i]); self.stream(f[i:])
                self.assertEqual(self.count(), before+1)
                self.assertEqual(self.mailbox(), payload(30))

    def test_invalid_feed_cannot_refresh_or_reuse_old_bytes(self):
        self.lib.HostKmFeed(payload(), 26)
        initial = self.mailbox(), self.count(), self.count('HOST_KM_RX_TIME')
        self.lib.advance(25)
        bads = [payload()[:i] for i in range(26)] + [payload(31)]
        for pos, val in [(0,0),(4,2),(5,1),(5,2),(16,8),(17,2),(18,1),(29,1)]:
            b = bytearray(payload(30)); b[pos] = val; bads.append(bytes(b))
        for b in bads:
            self.lib.HostKmFeed(b,len(b))
            self.assertEqual((self.mailbox(),self.count(),self.count('HOST_KM_RX_TIME')), initial)
        self.lib.HostKmFeed(None,26)
        self.assertEqual(self.count(),1)

    def test_critical_sections_restore_prior_mask(self):
        for mask in [0,1]:
            self.lib.mask_set(mask)
            self.lib.HostKmFeed(payload(),26)
            self.assertEqual(self.lib.mask_get(),mask)
            self.assertEqual(self.lib.alive(),1)
            self.assertEqual(self.lib.mask_get(),mask)
            self.lib.HostKmFeed(b'bad',3)
            self.assertEqual(self.lib.mask_get(),mask)

    def test_snapshot_freshness_expires(self):
        self.lib.HostKmFeed(payload(),26)
        self.assertEqual(self.lib.alive(),1)
        self.lib.advance(300)
        self.assertEqual(self.lib.alive(),1)
        self.lib.advance(1)
        self.assertEqual(self.lib.alive(),0)
        self.lib.HostKmFeed(payload(),26)
        self.assertEqual(self.lib.alive(),1)

    def test_alive_false_is_valid_but_inert(self):
        b=bytearray(payload()); b[17]=0
        self.lib.HostKmFeed(bytes(b),len(b))
        self.assertEqual(self.count(),1)
        self.assertEqual(self.lib.alive(),0)

    def test_crc_corruption_and_overlap_recovery(self):
        good=frame(payload())
        for pos in [4,12,len(good)-1]:
            bad=bytearray(good); bad[pos]^=1
            before=self.count(); self.stream(bytes(bad)+good)
            self.assertEqual(self.count(),before+1)
        for noise in [b'noise\xa5', b'\xa5\xa5\xa5',good[:15]]:
            before=self.count(); self.stream(noise+good)
            self.assertEqual(self.count(),before+1)

    def test_uint16_length_wrap_and_oversize(self):
        good=frame(payload())
        for length in [301,512,65527,65528,65535]:
            h=bytearray(struct.pack('<BHB',0xa5,length,0));h.append(crc(h,255,0x8c))
            before=self.count(); self.stream(bytes(h)+good)
            self.assertEqual(self.count(),before+1)

    def test_other_kind_other_command_and_short_frame(self):
        for bad in [frame(payload(),0x309),frame(payload()[:8]),frame(payload(31)),frame(b'PRM1\x01\x02'+b'\0'*24)]:
            self.stream(bad)
            self.assertEqual(self.count(),0)
        self.stream(frame(payload()))
        self.assertEqual(self.count(),1)

    def test_valid_outer_frame_cannot_inject_embedded_km(self):
        good=frame(payload())
        for cmd in [0x310,0x309,0x311]:
            data=b'x'*20 + good + b'x'*(300-20-len(good))
            self.stream(frame(data,cmd))
            self.assertEqual(self.count(),0)
        self.stream(good)
        self.assertEqual(self.count(),1)

    def test_partial_timeout_reconnect_and_tick_wrap(self):
        self.stream(frame(payload())[:10]); self.lib.advance(301)
        self.stream(frame(payload()));self.assertEqual(self.count(),1)
        self.lib.advance(0xfffffff0)
        self.stream(frame(payload())[:10]); self.lib.advance(301)
        self.stream(frame(payload()));self.assertEqual(self.count(),2)

    def test_host_typed_length_reserved_and_command(self):
        def host(body):
            b=bytearray([0x5a,len(body)+4,4]);b.append(crc(b,255,0x8c))
            b.extend(b'\0'*4+body);b.extend(struct.pack('<H',crc(b,65535,0x8408)))
            return bytes(b)
        for body in [b'',b'\1',b'\1\0\0',b'\1\0\0\0\0',b'\3\0\0\0',b'\1\2\0\0']:
            f=host(body);self.lib.bridge(f,len(f));self.assertEqual(self.count('HOST_SPIN_CMD_TIME'),0)
        f=host(b'\1\0\0\0')
        for split in range(len(f)):
            self.lib.bridge(f[:split],split)
            self.assertEqual(self.count('HOST_SPIN_CMD_TIME'),0)
        self.lib.bridge(f,len(f));self.assertEqual(self.count('HOST_SPIN_CMD_TIME'),1000)
        self.lib.advance(1)
        f=host(b'\1\1\0\0')  # Existing gimbal-host request bit is permitted.
        self.lib.bridge(f,len(f));self.assertEqual(self.count('HOST_SPIN_CMD_TIME'),1001)

    def test_referee_patch_upgrades_and_is_idempotent(self):
        old='#include "protocol.h"\nrobot_custom_data_3_t robot_custom_data_3;\n'+ 'memcpy(&robot_custom_data_3, frame + index, sizeof(robot_custom_data_3_t));\n'
        for stamped in [False,True]:
            text=old
            if stamped:
                text += ('            /* POLAR-KM-LINK: 记 0x0311 到达时刻，仲裁按它做新鲜度门控 */\n'
                         '            HOST_KM_RX_TIME = HAL_GetTick();\n            HOST_KM_RX_COUNT++;\n')
            p=Path(self.tmp.name)/'referee.c';p.write_text(text)
            # This small fixture isolates the KM upgrade. Full dispatcher shape
            # and integration are exercised by referee_rx/test_referee_rx.py.
            sys.path.insert(0,str(HERE.parent))
            with patch('referee_rx.apply_referee_rx.patch_referee_payload_dispatch', lambda text,log:text):
                result=km.apply_referee(p,[]);p.write_text(result)
                self.assertEqual(result,km.apply_referee(p,[]))
            self.assertNotIn('memcpy(&robot_custom_data_3',result)
            self.assertEqual(result.count('HostKmFeed(frame + index'),1)

if __name__ == '__main__':
    unittest.main()
