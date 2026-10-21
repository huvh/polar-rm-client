"""Backend early role/value checks and confirmed context forwarding."""
from pathlib import Path
import sys
import unittest
from types import SimpleNamespace
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from rm_client.backend.manager import BackendManager
from rm_client.backend.referee.registry import get_profile
from rm_client.referee_profiles import V2_PROFILE,DEFAULT_PROFILE
class ManagerAdmissionTests(unittest.TestCase):
    def host(self,robot):
        host=SimpleNamespace(referee=get_profile(V2_PROFILE),state=SimpleNamespace(robot_id=robot),mqtt=SimpleNamespace(client_id=str(robot)))
        host._v2_action_admission=lambda name,**kw:BackendManager._v2_action_admission(host,name,**kw)
        host.sent=[];host._publish=lambda *a,**kw:(host.sent.append((a,kw)) or (True,'ok'))
        return host
    def test_action_role_and_enum_matrix(self):
        for robot,method,args in ((2,'publish_assembly_command',(0,4)),(1,'publish_hero_deploy',(1,)),(3,'publish_rune_activate',(1,)),(6,'publish_dart_command',(5,False,False))):
            host=self.host(robot);self.assertTrue(getattr(BackendManager,method)(host,*args)[0]);self.assertEqual(len(host.sent),1)
            wrong=self.host(9);self.assertFalse(getattr(BackendManager,method)(wrong,*args)[0]);self.assertEqual(wrong.sent,[])
    def test_types_cannot_be_codec_coerced(self):
        cases=((2,'publish_assembly_command',(True,4)),(2,'publish_assembly_command',(0,5)),(3,'publish_rune_activate',(0,)),(6,'publish_dart_command',(1,1,False)),(1,'publish_hero_deploy',('1',)))
        for robot,method,args in cases:
            host=self.host(robot);self.assertFalse(getattr(BackendManager,method)(host,*args)[0]);self.assertEqual(host.sent,[])
    def test_performance_modes_and_token_route(self):
        for robot,values in ((1,(3,4,0)),(3,(1,2,0)),(6,(0,0,1))):
            host=self.host(robot);self.assertTrue(BackendManager.publish_robot_performance(host,*values,qualification_token='t')[0]);self.assertEqual(host.sent[0][1]['qualification_token'],'t')
        for robot,values in ((1,(1,2,0)),(3,(3,4,0)),(7,(0,0,1)),(6,(1,0,1))):
            self.assertFalse(BackendManager.publish_robot_performance(self.host(robot),*values)[0])
    def test_snapshot_forwarded_without_copy(self):
        host=self.host(6);snapshot=object()
        BackendManager.publish_sentry_command(host,1,qualification_token='token',expected_economy_snapshot=snapshot)
        self.assertIs(host.sent[0][1]['expected_economy_snapshot'],snapshot)
        self.assertEqual(host.sent[0][1]['intent'],'economy')
    def test_v1_mapping_unchanged_v2_aerial_controls_sentry(self):
        def registry(role):
            values={'Role':role,'Sentinel Control':'SemiAuto'}
            return SimpleNamespace(get=lambda name:SimpleNamespace(get_setting=lambda key:SimpleNamespace(value=values.get(key,''))))
        self.assertEqual(BackendManager.performance_values(registry('Sentinel'))['sentry_control'],1)
        self.assertEqual(BackendManager.performance_values(registry('Aerial'),referee_profile=V2_PROFILE),{'shooter':0,'chassis':0,'sentry_control':1})
        self.assertEqual(BackendManager.performance_values(registry('Sentinel'),referee_profile=V2_PROFILE)['sentry_control'],0)
    def test_economic_integer_arguments_are_not_silently_coerced(self):
        for method,robot,args in (("publish_common_command",3,(True,10)),("publish_common_command",3,(1,10.5)),("publish_sentry_command",6,(1.5,)),("publish_air_support",6,("2",))):
            host=self.host(robot)
            self.assertFalse(getattr(BackendManager,method)(host,*args)[0])
            self.assertEqual(host.sent,[])
    def test_runtime_identity_mismatch_is_rejected(self):
        host=self.host(2);host.mqtt.client_id='102'
        self.assertFalse(BackendManager.publish_assembly_command(host,0,1)[0])
if __name__=='__main__':unittest.main()
