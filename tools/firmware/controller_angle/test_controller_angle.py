#!/usr/bin/env python3
"""Compile real patched source against read-only StandardRobot++ 2722e0d types.

POLAR_REFEREE_REFERENCE chooses the reference. All modified fixtures are temporary.
No firmware task, hardware port, board flash, or network service is used.
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
ROOT = Path(os.environ.get("POLAR_REFEREE_REFERENCE", HERE / ".no-reference"))
sys.path.insert(0, str(HERE))
import apply_controller_angle as angle


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


km = load("controller_angle_km", HERE.parent / "km_link/apply_km_link.py")


def function(text, name):
    match = re.search(r"^(?:static )?(?:void|bool|uint8_t|float) " + name + r"\([^\n]*\)\s*\{.*?^\}", text, re.M | re.S)
    if not match:
        raise AssertionError("missing function " + name)
    return match.group()


class ControllerAngleFirmware(unittest.TestCase):
    def setUp(self):
        if not (ROOT / angle.OWNED[0]).is_file():
            self.skipTest("select a read-only StandardRobot++ reference with POLAR_REFEREE_REFERENCE")

    def compile_run(self, source, extra=None):
        cc = shutil.which("cc")
        if not cc:
            self.skipTest("portable C compiler not installed")
        with tempfile.TemporaryDirectory(prefix="polar-angle-c-") as temporary:
            temp = Path(temporary)
            (temp / "main.h").write_text("/* Hardware-free header shim. */\n")
            (temp / "referee.h").write_text(angle.patch_header((ROOT / angle.OWNED[1]).read_text()))
            if extra:
                for name, text in extra.items():
                    (temp / name).write_text(text)
            (temp / "test.c").write_text(source)
            exe = temp / "test"
            command = [cc, "-std=c11", "-Wall", "-Wextra", "-Werror", "-fsanitize=" + os.environ.get("POLAR_REFEREE_SANITIZERS", "undefined,bounds"), "-fno-sanitize-recover=all", "-I", str(temp), "-I", str(ROOT / "application/referee"), "-I", str(ROOT / "application/typedef"), str(temp / "test.c"), "-lm", "-o", str(exe)]
            subprocess.run(command, check=True)
            result = subprocess.run([str(exe)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            print(result.stdout.strip())

    def test_real_dispatch_freshness_and_snapshot(self):
        original = (ROOT / angle.OWNED[0]).read_text()
        patched = angle.patch_referee(km.apply_referee(ROOT / angle.OWNED[0], []))
        globals_text = original[original.index("#define REFEREE_TIMEOUT"):original.index("void init_referee_struct_data")]
        header = (HERE.parent / "km_link/host_km_link.h").read_text()
        km_types = header[header.index("#define PRM1_MAGIC_0"):header.index("typedef char HOST_KM_STATIC_ASSERT_size")]
        body = r'''
#include <limits.h>
#include <assert.h>
#include <string.h>
#include <stdio.h>
#include <stdlib.h>
#define __packed
#define __packed__ __attribute__((packed))
#define inline
#pragma pack(push, 1)
#include "referee.h"
#undef inline
#pragma pack(pop)
_Static_assert(sizeof(float)==4, "binary32 contract");
static uint32_t now, irq;
uint32_t HAL_GetTick(void) {return now;}
uint32_t __get_PRIMASK(void) {return irq;}
void __disable_irq(void) {irq=1;}
void __set_PRIMASK(uint32_t value) {irq=value;}
#define HOST_KM_CRITICAL_ENTER() 0U
#define HOST_KM_CRITICAL_EXIT(value) ((void)value)
volatile uint32_t HOST_KM_RX_TIME, HOST_KM_RX_COUNT;
'''
        body += globals_text + km_types + "\n" + angle.IMPLEMENTATION
        body += function(km.RC_IMPL, "HostKmPayloadValid") + "\n" + function(km.RC_IMPL, "HostKmFeed") + "\n"
        body += function(patched, "init_referee_struct_data") + "\n" + function(patched, "referee_data_solve")
        body += r'''
static void dispatch(uint16_t cmd, const void *payload, uint16_t size) {
    uint8_t *frame=calloc((size_t)size+9U,1U); assert(frame);
    frame[0]=0xA5;frame[1]=(uint8_t)size;frame[2]=(uint8_t)(size>>8);
    frame[5]=(uint8_t)cmd;frame[6]=(uint8_t)(cmd>>8);
    if(payload) memcpy(frame+7,payload,size);
    referee_data_solve(frame);free(frame);
}
int main(void) {
    float expected[6]={0.1f,0.2f,-0.3f,0.4f,0.5f,-0.6f};
    float actual[6], untouched[6];uint8_t data[64]={0}, km_data[30]={0};
    uint32_t i, stamp, valid_count;
    memset(actual,0x37,sizeof(actual));memcpy(untouched,actual,sizeof(actual));
    now=0;init_referee_struct_data();
    assert(!GetCustomControllerOnline());
    assert(!GetCustomControllerAngles(actual) && !memcmp(actual,untouched,sizeof(actual)));
    assert(GetCustomControllerPos(0)==0 && GetCustomControllerPos(255)==0);
    memcpy(data,expected,sizeof(expected));
    /* The source's legacy noncanonical tail is ignored; no seventh axis exists. */
    memset(data+24,0xAA,6);
    dispatch(CUSTOM_CONTROLLER_CMD_ID,data,30);
    assert(GetCustomControllerOnline() && controller_angle_valid && controller_angle_time==0);
    assert(GetCustomControllerAngles(actual) && !memcmp(actual,expected,sizeof(actual)));
    for(i=0;i<6;i++) assert(GetCustomControllerPos(i)==expected[i]);
    assert(GetCustomControllerPos(6)==0 && GetCustomControllerPos(255)==0);
    irq=1;assert(GetCustomControllerAngles(actual));assert(irq==1);irq=0;
    /* Every malformed length and every nonfinite axis must preserve the mailbox. */
    stamp=controller_angle_time;now=50;
    for(i=0;i<64;i++) if(i!=30) {
        dispatch(CUSTOM_CONTROLLER_CMD_ID,data,(uint16_t)i);
        assert(controller_angle_time==stamp && !memcmp(controller_angle_sample,expected,sizeof(expected)));
    }
    for(i=0;i<6;i++) {
        uint32_t bad[3]={0x7f800000U,0xff800000U,0x7fc00001U};unsigned j;
        for(j=0;j<3;j++) {
            memcpy(data+4*i,&bad[j],4);dispatch(CUSTOM_CONTROLLER_CMD_ID,data,30);
            assert(controller_angle_time==stamp && !memcmp(controller_angle_sample,expected,sizeof(expected)));
        }
        memcpy(data+4*i,&expected[i],4);
    }
    for(i=0;i<6;i++) {
        float bad=controller_angle_max[i]+0.001f;
        memcpy(data+4*i,&bad,4);dispatch(CUSTOM_CONTROLLER_CMD_ID,data,30);
        assert(controller_angle_time==stamp);
        bad=controller_angle_min[i]-0.001f;
        memcpy(data+4*i,&bad,4);dispatch(CUSTOM_CONTROLLER_CMD_ID,data,30);
        assert(controller_angle_time==stamp);
        memcpy(data+4*i,&expected[i],4);
    }
    memcpy(km_data,"PRM1",4);km_data[4]=1;km_data[5]=3;km_data[17]=1;
    for(now=100;now<=200;now+=100) {
        valid_count=HOST_KM_RX_COUNT;
        dispatch(ROBOT_CUSTOM_DATA_3_CMD_ID,km_data,30);
        assert(HOST_KM_RX_COUNT==valid_count+1 && HOST_KM_RX_TIME==now);
        dispatch(ROBOT_CUSTOM_DATA_CMD_ID,data,30);
        dispatch(GAME_RESULT_CMD_ID,data,sizeof(game_result_t));
        assert(referee_online_time==now && controller_angle_time==stamp);
    }
    now=299;assert(GetCustomControllerOnline());
    now=300;memcpy(actual,untouched,sizeof(actual));
    assert(!GetCustomControllerAngles(actual) && !memcmp(actual,untouched,sizeof(actual)));
    assert(!controller_angle_valid && GetCustomControllerPos(1)==0);
    for(now=300;now<=400;now+=100) {
        dispatch(ROBOT_CUSTOM_DATA_3_CMD_ID,km_data,30);
        dispatch(ROBOT_CUSTOM_DATA_CMD_ID,data,30);
        dispatch(GAME_RESULT_CMD_ID,data,sizeof(game_result_t));
        assert(referee_online_time==now && controller_angle_time==stamp);
        assert(!GetCustomControllerOnline());
    }
    /* Fresh angles recover; old unrelated payloads do not. */
    now=600;dispatch(CUSTOM_CONTROLLER_CMD_ID,data,30);
    assert(GetCustomControllerAngles(actual) && !memcmp(actual,expected,sizeof(actual)));
    /* Both receive and age subtraction are valid across uint32 millisecond wrap. */
    now=0xFFFFFFFFU-100U;dispatch(CUSTOM_CONTROLLER_CMD_ID,data,30);
    now=198;assert(GetCustomControllerOnline());
    now=199;assert(!GetCustomControllerOnline());
    now=0xFFFFFFFFU-100U;assert(!GetCustomControllerOnline());
    now=3;dispatch(CUSTOM_CONTROLLER_CMD_ID,data,30);assert(GetCustomControllerOnline());
    init_referee_struct_data();assert(!GetCustomControllerOnline());
    assert(!CustomControllerAnglesAccept(NULL,30));
    memcpy(data,controller_angle_min,sizeof(controller_angle_min));
    assert(CustomControllerAnglesAccept(data,30));
    assert(GetCustomControllerAngles(actual) && !memcmp(actual,controller_angle_min,sizeof(actual)));
    memcpy(data,controller_angle_max,sizeof(controller_angle_max));
    assert(CustomControllerAnglesAccept(data,30));
    assert(GetCustomControllerAngles(actual) && !memcmp(actual,controller_angle_max,sizeof(actual)));
    puts("PASS: real 0x0302 dispatch, finite checks, independent timeout, KM isolation, startup, wrap and recovery");
    return 0;
}
'''
        self.compile_run(body)

    def test_installer_idempotence_and_revert_preserves_edits(self):
        with tempfile.TemporaryDirectory(prefix="polar-angle-fixture-") as temporary:
            root=Path(temporary)
            subprocess.run(["git","init","-q",str(root)],check=True)
            originals={}
            for rel in angle.OWNED:
                path=root/rel;path.parent.mkdir(parents=True,exist_ok=True)
                originals[rel]=(ROOT/rel).read_bytes();path.write_bytes(originals[rel])
            self.assertEqual(angle.main([str(root),"--dry-run"]),0)
            self.assertTrue(all((root/rel).read_bytes()==data for rel,data in originals.items()))
            self.assertEqual(angle.main([str(root)]),0)
            installed={rel:(root/rel).read_bytes() for rel in angle.OWNED}
            self.assertEqual(angle.main([str(root)]),0)
            self.assertTrue(all((root/rel).read_bytes()==data for rel,data in installed.items()))
            # Refuse whole-operation rollback if any later user edit would be lost.
            (root/angle.OWNED[2]).write_bytes(installed[angle.OWNED[2]]+b"\n/* later edit */\n")
            self.assertEqual(angle.main([str(root),"--revert"]),2)
            (root/angle.OWNED[2]).write_bytes(installed[angle.OWNED[2]])
            self.assertEqual(angle.main([str(root),"--revert"]),0)
            self.assertTrue(all((root/rel).read_bytes()==data for rel,data in originals.items()))

    def test_bounded_sender_and_rate_block(self):
        source=angle.patch_sender((ROOT/angle.OWNED[3]).read_text())
        task=angle.patch_task((ROOT/angle.OWNED[4]).read_text())
        cadence=re.search(r'        if \(\(uint32_t\)\(xTaskGetTickCount\(\) - lastTick\).*?\n        \}',task,re.S).group()
        body=r'''
#include <stdint.h>
#include <assert.h>
#include <string.h>
#include <stdio.h>
#include <stdlib.h>
#define CUSTOM_CONTROLLER_ANGLE_COUNT 6U
#define DATA_LENGTH 30U
#define DATA_FRAME_LENGTH 39U
#define CONTROLLER_CMD_ID 0x0302U
#define CUSTOM_CONTROLLER_SEND_TIME 34U
#pragma pack(push,1)
typedef struct {struct{uint8_t sof;uint16_t data_length;uint8_t seq,crc8;}frame_header;uint16_t cmd_id;uint8_t data[30];uint16_t frame_tail;}Controller_t;
#pragma pack(pop)
static Controller_t TX_DATA, sent;
static int huart1;
static uint32_t now,lastTick,send_count;
static struct {float pos[7];}cc_control_data;
static uint32_t xTaskGetTickCount(void){return now;}
static void append_CRC8_check_sum(uint8_t*p,unsigned n){assert(n==5);p[n-1]=7;}
static void append_CRC16_check_sum(uint8_t*p,unsigned n){assert(n==39);p[n-1]=8;}
static void HAL_UART_Transmit(int*h,uint8_t*p,unsigned n,unsigned timeout){assert(h==&huart1&&n==39&&timeout==50);memcpy(&sent,p,n);send_count++;}
'''
        body+=function(source,"DataConcatenat")+"\n"+function(source,"SendDataToPC")
        body+="\nstatic void tick(void){\n"+cadence+"\n}\n"
        body+=r'''
int main(void){
    unsigned i;float *six=malloc(6*sizeof(float));assert(six);
    for(i=0;i<6;i++)six[i]=(float)i;
    SendDataToPC((uint8_t*)six);
    assert(!memcmp(sent.data,six,24));
    for(i=24;i<30;i++)assert(sent.data[i]==0);
    assert(sent.cmd_id==0x0302 && sent.frame_header.data_length==30);
    SendDataToPC(NULL);assert(send_count==1);free(six);
    send_count=0;now=33;tick();assert(send_count==0);
    now=34;tick();assert(send_count==1&&lastTick==34);
    for(now=35;now<68;now++){tick();}
    assert(send_count==1);
    now=68;tick();assert(send_count==2&&lastTick==68);
    lastTick=UINT32_MAX-10U;now=22;tick();assert(send_count==2);
    now=23;tick();assert(send_count==3&&lastTick==23);
    puts("PASS: sender reads only six floats, zeroes reserved tail, preserves frame ABI, enforces 34 ms across wrap");
    return 0;
}
'''
        self.compile_run(body)

    def test_real_arm_snapshot_and_output_expiry(self):
        patched=angle.patch_arm((ROOT/angle.OWNED[2]).read_text())
        reference=function(patched,"MechanicalArmReference")
        start=reference.index("        case MECHANICAL_ARM_FOLLOW: {")
        end=reference.index("        case MECHANICAL_ARM_CALIBRATE:",start)
        follow=reference[start:end]
        console=function(patched,"MechanicalArmConsole")
        gate=console[console.index("{")+1:console.index("    switch (MECHANICAL_ARM.mode)")]
        body=r'''
#include <stdint.h>
#include <stdbool.h>
#include <math.h>
#include <string.h>
#include <stdio.h>
#include <assert.h>
static uint32_t now,irq;
static uint32_t HAL_GetTick(void){return now;}
static uint32_t __get_PRIMASK(void){return irq;}
static void __disable_irq(void){irq=1;}
static void __set_PRIMASK(uint32_t value){irq=value;}
'''
        body+=angle.DECLARATIONS+angle.IMPLEMENTATION
        body+=r'''
enum {J0,J1,J2,J3,J4,J5};
enum {MECHANICAL_ARM_SAFE,MECHANICAL_ARM_FOLLOW};
#define CUSTOM_CONTROLLER_DATA_ERROR_OFFSET 4U
static struct {
    bool custom_controller_ready;
    unsigned mode,error_code;
    struct {struct {float angle;}joint[6];}ref;
    struct {struct {float pos[6],vj4_pos,vj5_pos;}min,max;}limit;
}MECHANICAL_ARM;
#define MA MECHANICAL_ARM
static float fp32_constrain(float value,float min,float max){return value<min?min:(value>max?max:value);}
'''
        body+="static void reference(void){switch(MA.mode){\n"+follow+"\ndefault:break;}}\n"
        body+="static void output_gate(void){\n"+gate+"\n}\n"
        body+=r'''
int main(void){
    float joints[6]={0.1f,0.2f,-0.3f,0.4f,0.5f,-0.6f};
    uint8_t payload[30]={0};unsigned i;
    for(i=0;i<6;i++){MA.limit.min.pos[i]=-30;MA.limit.max.pos[i]=30;MA.ref.joint[i].angle=0;}
    MA.limit.min.vj4_pos=-1;MA.limit.max.vj4_pos=1;
    MA.limit.min.vj5_pos=-2;MA.limit.max.vj5_pos=2;
    CustomControllerAnglesReset();MA.mode=MECHANICAL_ARM_FOLLOW;
    reference();assert(!MA.custom_controller_ready && MA.mode==MECHANICAL_ARM_SAFE);
    for(i=0;i<6;i++)assert(MA.ref.joint[i].angle==0);
    memcpy(payload,joints,24);assert(CustomControllerAnglesAccept(payload,30));
    MA.mode=MECHANICAL_ARM_FOLLOW;reference();
    assert(MA.custom_controller_ready && MA.mode==MECHANICAL_ARM_FOLLOW && MA.error_code==0);
    for(i=0;i<6;i++)assert(fabsf(MA.ref.joint[i].angle-joints[i])<0.00001f);
    now=299;output_gate();assert(MA.mode==MECHANICAL_ARM_FOLLOW);
    now=300;output_gate();assert(MA.mode==MECHANICAL_ARM_SAFE && !MA.custom_controller_ready);
    for(i=0;i<6;i++)assert(fabsf(MA.ref.joint[i].angle-joints[i])<0.00001f);
    MA.mode=MECHANICAL_ARM_FOLLOW;reference();assert(MA.mode==MECHANICAL_ARM_SAFE);
    now=301;joints[0]=0.2f;memcpy(payload,joints,24);
    assert(CustomControllerAnglesAccept(payload,30));MA.mode=MECHANICAL_ARM_FOLLOW;
    reference();output_gate();assert(MA.mode==MECHANICAL_ARM_FOLLOW && MA.custom_controller_ready);
    assert(MA.ref.joint[J0].angle==0.2f);
    /* Existing position-jump error remains latched and is not cleared by RX. */
    joints[0]=2.0f;memcpy(payload,joints,24);assert(CustomControllerAnglesAccept(payload,30));
    reference();assert(MA.error_code & CUSTOM_CONTROLLER_DATA_ERROR_OFFSET);
    assert(MA.ref.joint[J0].angle==0.2f);
    puts("PASS: actual arm FOLLOW branch uses one fresh snapshot; startup/stale reaches existing SAFE and valid frames recover without bypassing jump gate");
    return 0;
}
'''
        self.compile_run(body)

    def test_km_install_order_compatible(self):
        original=(ROOT/angle.OWNED[0]).read_text()
        with tempfile.TemporaryDirectory() as temporary:
            path=Path(temporary)/"referee.c"
            # Both orderings must preserve the two independent validators.
            for source in (original, km.apply_referee(ROOT/angle.OWNED[0], [])):
                patched=angle.patch_referee(source)
                path.write_text(patched)
                patched=km.apply_referee(path,[])
                self.assertEqual(patched,angle.patch_referee(patched))
                self.assertIn("if (!HostKmFeed(frame + index, payload_length)) return;",patched)
                self.assertIn("if (!CustomControllerAnglesAccept(frame + index,",patched)


if __name__=="__main__":
    if not (ROOT/angle.OWNED[0]).is_file():
        print("SKIP: set POLAR_REFEREE_REFERENCE to a read-only StandardRobot++ checkout")
        raise SystemExit(77)
    unittest.main()
