"""Compile patched real dispatch and declarations; never build external firmware.

Set POLAR_REFEREE_REFERENCE to a read-only StandardRobot++ checkout.
"""
from __future__ import annotations
import importlib.util
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = Path(__file__).resolve().parent

def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

rx = load('referee_guard_patch', HERE / 'apply_referee_rx.py')
km = load('referee_km_patch', HERE.parent / 'km_link/apply_km_link.py')


def function(text, name):
    found = re.search(r'^(?:static )?(?:void|uint8_t) ' + name + r'\([^\n]*\)\s*\{.*?^\}', text, re.M | re.S)
    if not found:
        raise AssertionError(name + ' missing')
    return found.group()


class RefereePayloadDispatch(unittest.TestCase):
    def test_real_dispatch_all_active_payloads(self):
        root = Path(os.environ.get('POLAR_REFEREE_REFERENCE', HERE.parents[2] / '.firmware-not-selected'))
        ref = root / 'application/referee/referee.c'
        if not ref.is_file():
            self.skipTest('read-only reference absent; set POLAR_REFEREE_REFERENCE')
        cc = shutil.which('cc')
        if not cc:
            self.skipTest('portable C compiler absent')
        original = ref.read_text()
        # Use the public installer as integrated, or install just its handoff first.
        patched = km.apply_referee(ref, [])
        patched = rx.patch_referee_payload_dispatch(patched, [])
        self.assertEqual(patched, rx.patch_referee_payload_dispatch(patched, []))
        with tempfile.TemporaryDirectory() as check:
            repeated = Path(check) / 'referee.c'
            repeated.write_text(patched)
            self.assertEqual(patched, km.apply_referee(repeated, []))
        cases = re.findall(r'^        case (\w+): \{\s*memcpy\(&(\w+), frame \+ index, sizeof\((\w+)\)\);', function(original, 'referee_data_solve'), re.M)
        self.assertEqual(len(cases), 24)
        fixed = [(cmd, obj, typ) for cmd, obj, typ in cases if cmd not in ('STUDENT_INTERACTIVE_DATA_CMD_ID', 'ROBOT_CUSTOM_DATA_3_CMD_ID')]
        state_objects = [obj for _, obj, _ in cases] + ['referee_receive_header', 'referee_receive_count', 'referee_online_time', 'HOST_KM_RX_TIME', 'HOST_KM_RX_COUNT']
        save = '\n'.join(f'memcpy(out + n, (const void *)&{obj}, sizeof({obj})); n += sizeof({obj});' for obj in state_objects)
        globals_text = original[original.index('#define REFEREE_TIMEOUT'):original.index('void init_referee_struct_data')]
        header = (HERE.parent / 'km_link/host_km_link.h').read_text()
        km_types = header[header.index('#define PRM1_MAGIC_0'):header.index('typedef char HOST_KM_STATIC_ASSERT_size')]
        body = r'''
#include <assert.h>
#include <stdlib.h>
#include <stdio.h>
#include <string.h>
#define __packed
#define __packed__ __attribute__((packed))
#define inline
#pragma pack(push, 1)
#include "referee.h"
#undef inline
#pragma pack(pop)
_Static_assert(sizeof(frame_header_struct_t) == 5, "header ABI");
_Static_assert(sizeof(game_status_t) == 11, "packed ABI");
_Static_assert(sizeof(robot_interaction_data_t) == 118, "interaction ABI");
static uint32_t now = 1000;
uint32_t HAL_GetTick(void) { return now; }
#define HOST_KM_CRITICAL_ENTER() 0U
#define HOST_KM_CRITICAL_EXIT(saved) ((void)(saved))
volatile uint32_t HOST_KM_RX_TIME, HOST_KM_RX_COUNT;
'''
        body += globals_text + km_types + '\n'
        body += function(km.RC_IMPL, 'HostKmPayloadValid') + '\n' + function(km.RC_IMPL, 'HostKmFeed') + '\n'
        body += function(patched, 'referee_data_solve') + '\n'
        body += 'static size_t snapshot(unsigned char *out) {size_t n=0;\n' + save + '\nreturn n;}\n'
        body += r'''
static void dispatch(unsigned cmd, unsigned size, const unsigned char *data) {
    unsigned char *frame = calloc(size + 9U, 1U);
    assert(frame);
    frame[0]=0xA5; frame[1]=size; frame[2]=size>>8; frame[3]=17;
    frame[5]=cmd; frame[6]=cmd>>8;
    if (data) memcpy(frame+7, data, size); else memset(frame+7, 0xA6, size);
    referee_data_solve(frame);
    free(frame);
}
static void rejected(unsigned cmd, unsigned size, const unsigned char *data) {
    unsigned char before[2048], after[2048]; size_t n=snapshot(before);
    dispatch(cmd,size,data);
    assert(snapshot(after)==n && memcmp(before,after,n)==0);
}
int main(void) {
    unsigned n, previous_count; unsigned char data[119];
    referee_receive_count=19; referee_online_time=10;
'''
        for cmd, obj, typ in fixed:
            body += f'''    for(n=0; n<sizeof({typ})+3; n++) if(n!=sizeof({typ})) rejected({cmd},n,NULL);
    rejected({cmd},119,NULL); rejected({cmd},65535,NULL);
    previous_count = (now - referee_online_time > REFEREE_TIMEOUT) ? 0 : referee_receive_count;
    dispatch({cmd},sizeof({typ}),NULL);
    assert(referee_online_time==now && referee_receive_count==previous_count+1);
    assert(referee_receive_header.data_length==sizeof({typ}) && referee_receive_header.seq==17);
    for(n=0;n<sizeof({obj});n++) assert(((unsigned char*)&{obj})[n]==0xA6);
    now+=401;
'''
        body += r'''
    rejected(STUDENT_INTERACTIVE_DATA_CMD_ID,0,NULL);
    rejected(STUDENT_INTERACTIVE_DATA_CMD_ID,5,NULL);
    rejected(STUDENT_INTERACTIVE_DATA_CMD_ID,119,NULL);
    for(n=6;n<=118;n++) {
        unsigned i; memset(&robot_interaction_data,0xCC,sizeof(robot_interaction_data));
        dispatch(STUDENT_INTERACTIVE_DATA_CMD_ID,n,NULL);
        for(i=0;i<sizeof(robot_interaction_data);i++)
            assert(((unsigned char*)&robot_interaction_data)[i]==(i<n?0xA6:0));
    }
    memset(data,0,sizeof(data)); memcpy(data,"PRM1",4); data[4]=1;data[5]=3;data[17]=1;
    for(n=0;n<26;n++) rejected(ROBOT_CUSTOM_DATA_3_CMD_ID,n,data);
    for(n=26;n<=30;n++) {
        unsigned previous=HOST_KM_RX_COUNT;
        dispatch(ROBOT_CUSTOM_DATA_3_CMD_ID,n,data);
        assert(HOST_KM_RX_COUNT==previous+1 && HOST_KM_RX_TIME==now);
        assert(referee_online_time==now);
    }
    for(n=31;n<=119;n++) rejected(ROBOT_CUSTOM_DATA_3_CMD_ID,n,data);
    for(n=0;n<30;n++) {
        unsigned char old=data[n];
        if(n<6 || n>=18) { data[n]^=0x80;rejected(ROBOT_CUSTOM_DATA_3_CMD_ID,30,data); }
        data[n]=old;
    }
    data[16]=8; rejected(ROBOT_CUSTOM_DATA_3_CMD_ID,26,data);data[16]=0;
    data[17]=2; rejected(ROBOT_CUSTOM_DATA_3_CMD_ID,26,data);data[17]=1;
    rejected(0xFFFF,30,data);
    {
        unsigned char before[2048],after[2048];size_t count=snapshot(before);
        referee_data_solve(NULL);assert(snapshot(after)==count && !memcmp(before,after,count));
    }
    puts("PASS: 22 fixed typed cases, 6..118 interactive, canonical 26..30 KM; rejected state unchanged");
    return 0;
}
'''
        with tempfile.TemporaryDirectory(prefix='polar-referee-rx-') as td:
            td = Path(td)
            (td / 'main.h').write_text('/* Portable header shim: hardware APIs unused by dispatched types. */\n')
            source = td / 'dispatch.c'
            source.write_text(body)
            exe = td / 'dispatch'
            subprocess.run([cc,'-std=c11','-Wall','-Wextra','-Werror','-fsanitize=' + os.environ.get('POLAR_REFEREE_SANITIZERS', 'undefined,bounds'), '-fno-sanitize-recover=all', '-I',str(td),'-I',str(root/'application/referee'),'-I',str(root/'application/typedef'),str(source),'-o',str(exe)],check=True)
            result = subprocess.run([str(exe)],capture_output=True,text=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            print(result.stdout.strip())

if __name__ == '__main__':
    reference = os.environ.get('POLAR_REFEREE_REFERENCE')
    if not reference:
        print('SKIP: set POLAR_REFEREE_REFERENCE to the explicitly selected read-only firmware reference')
        sys.exit(77)
    if not (Path(reference) / 'application/referee/referee.c').is_file():
        print('SKIP: selected firmware reference has no application/referee/referee.c')
        sys.exit(77)
    if not shutil.which('cc'):
        print('SKIP: portable C compiler cc is unavailable')
        sys.exit(77)
    unittest.main()
