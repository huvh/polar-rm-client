"""Local identity/round retirement witness; no transport or UI acquisition."""
from dataclasses import fields
import unittest
from rm_client.backend.referee.rm2026_v2.observations import WireSnapshot, observe
from rm_client.backend.referee.rm2026_v2 import codec
from rm_client.backend.referee.wire import encode_uint

class ScopeRevisionTests(unittest.TestCase):
    def receive(self, prior, message, pairs, *, at=100., generation=1):
        data=codec.decode_message(message,b''.join(encode_uint(n,v) for n,v in pairs))
        return observe(prior,profile_id='rm2026-v2.0.0',receive_generation=generation,
                       client_id='6',message=message,data=data,received_at=at)
    def bound(self):
        value=self.receive(None,'GameStatus',[(1,1)])
        return self.receive(value,'RobotStaticStatus',[(4,6),(5,91)])
    def test_old_positional_constructor_preserved_with_explicit_model_extension(self):
        value=WireSnapshot('rm2026-v2.0.0',1,'6',100.,())
        self.assertEqual(value.scope_revision,0)
        self.assertEqual([f.name for f in fields(WireSnapshot)][-1],'scope_revision')
    def test_first_scope_bindings_advance_only_once_per_record(self):
        value=self.receive(None,'GameStatus',[(5,4)])
        self.assertEqual(value.scope_revision,0)
        value=self.receive(value,'RobotStaticStatus',[(4,6),(5,91)])
        self.assertEqual(value.scope_revision,1)
        self.assertIsNone(value.get('GameStatus','current_stage'))
        value=self.receive(value,'GameStatus',[(1,1)])
        self.assertEqual(value.scope_revision,2)
        self.assertEqual(value.get('RobotStaticStatus','robot_id').value,6)
    def test_periodic_same_scope_and_non_scope_updates_preserve_revision(self):
        value=self.bound();revision=value.scope_revision
        for message,pairs in [('GameStatus',[(1,1),(5,4)]),('RobotStaticStatus',[(4,6),(5,91)]),('AirSupportStatusSync',[(1,1)])]:
            value=self.receive(value,message,pairs,at=101.)
            self.assertEqual(value.scope_revision,revision)
    def test_round_aba_cannot_reuse_original_witness(self):
        value=self.bound();original=value.scope_revision
        for round_id in (2,1): value=self.receive(value,'GameStatus',[(1,round_id)])
        self.assertEqual(value.get('GameStatus','current_round').value,1)
        self.assertEqual(value.scope_revision,original+2)
    def test_identity_and_type_aba_each_retire(self):
        for field,other in ((4,106),(5,92)):
            value=self.bound();original=value.scope_revision
            value=self.receive(value,'RobotStaticStatus',[(field,other)])
            value=self.receive(value,'RobotStaticStatus',[(field,6 if field==4 else 91)])
            self.assertEqual(value.scope_revision,original+2)
    def test_old_completion_and_empty_record_do_not_advance_or_repopulate(self):
        value=self.receive(self.bound(),'GameStatus',[(1,2)],at=102.)
        self.assertIs(self.receive(value,'GameStatus',[(1,1)],at=101.),value)
        self.assertIs(self.receive(value,'GameStatus',[],at=103.),value)
    def test_new_receive_context_is_separately_scoped(self):
        value=self.bound();new=self.receive(value,'GameStatus',[(1,1)],generation=2)
        self.assertEqual(new.scope_revision,1)
        self.assertNotEqual((new.receive_generation,new.scope_revision),(value.receive_generation,value.scope_revision))
        self.assertIsNone(new.get('RobotStaticStatus','robot_id'))

if __name__=='__main__': unittest.main()
