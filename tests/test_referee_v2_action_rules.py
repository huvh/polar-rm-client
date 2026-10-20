"""Pure V2 formula/member contracts; no profile activation or authority claims."""
import math
from fractions import Fraction
import unittest

from rm_client.backend.referee.rm2026_v2 import contract, economy_rules as rules


class V2ActionRulesTests(unittest.TestCase):
    def test_heal_boundaries(self):
        for remaining, cost in ((420,50),(419,51),(418,51),(417,51),(416,52),(361,70),(360,70),(359,71),(1,190),(0,190)):
            with self.subTest(remaining=remaining):
                self.assertEqual(rules.estimate_remote_heal_cost(remaining),cost)

    def test_heal_all_integer_seconds_against_fraction_oracle(self):
        for remaining in range(421):
            with self.subTest(remaining=remaining):
                self.assertEqual(rules.estimate_remote_heal_cost(remaining),50+math.ceil(Fraction((420-remaining)*20,60)))

    def test_revive_and_air_all_integer_seconds_and_levels(self):
        for remaining in range(421):
            for level in range(1,11):
                expected=math.ceil(Fraction(420-remaining,60))*80+level*20
                with self.subTest(remaining=remaining,level=level):
                    self.assertEqual(rules.estimate_leveled_revive_cost(remaining,level),expected)
                    self.assertEqual(rules.estimate_air_countermeasure_cost(remaining,level),2*expected)

    def test_air_release_examples(self):
        self.assertEqual(rules.estimate_air_countermeasure_cost(360,3),280)
        self.assertEqual(rules.estimate_air_countermeasure_cost(359,3),440)
        self.assertEqual(rules.estimate_air_countermeasure_cost(420,1),40)

    def test_missing_or_invalid_countdown_is_not_defaulted(self):
        for value in (None,True,False,-1,421,419.0,'419',float('nan'),float('inf'),[],{},10**100):
            for fn,args in ((rules.estimate_remote_heal_cost,()),(rules.estimate_leveled_revive_cost,(3,)),(rules.estimate_air_countermeasure_cost,(3,))):
                with self.subTest(value=repr(value),function=fn.__name__):
                    with self.assertRaises(ValueError):fn(value,*args)

    def test_missing_or_invalid_level_is_not_defaulted(self):
        for value in (None,True,False,0,-1,11,3.0,'3',float('nan'),float('inf'),[],{},10**100):
            for fn in (rules.estimate_leveled_revive_cost,rules.estimate_air_countermeasure_cost):
                with self.subTest(value=repr(value),function=fn.__name__):
                    with self.assertRaises(ValueError):fn(360,value)

    def test_no_implicit_arguments(self):
        for fn in (rules.estimate_remote_heal_cost,rules.estimate_leveled_revive_cost,rules.estimate_air_countermeasure_cost):
            with self.subTest(function=fn.__name__):
                with self.assertRaises(TypeError):fn()

    def test_sentry_exact_documented_membership(self):
        expected={1,3,4,5,6,7,8,9,10,11,12}
        for value in range(-1,15):
            self.assertEqual(rules.is_documented_command('SentryCtrlCommand',value),value in expected)

    def test_air_exact_documented_membership(self):
        for value in range(-1,6):
            self.assertEqual(rules.is_documented_command('AirSupportCommand',value),value in {0,1,2,3})

    def test_command_types_and_unknown_topics_fail_closed(self):
        for topic in ('Unknown','CommonCommand','sentryctrlcommand','',None,[],1):
            self.assertFalse(rules.is_documented_command(topic,1))
        for value in (True,False,1.0,'1',None,[],{},float('nan')):
            for topic in ('SentryCtrlCommand','AirSupportCommand'):
                self.assertFalse(rules.is_documented_command(topic,value))

    def test_rate_contract_does_not_invent_air_limit(self):
        self.assertEqual(contract.TOPICS['SentryCtrlCommand'],('uplink','触发≤10Hz','2.2.33'))
        self.assertEqual(contract.TOPICS['AirSupportCommand'],('uplink','触发式','2.2.35'))
        self.assertEqual(contract.MAX_QOS,1)

    def test_rule_provenance_and_no_action_admission_api(self):
        self.assertEqual(rules.RULES_VERSION,'2.2.0 (2026-08-07)')
        self.assertEqual(rules.RULES_SHA256,'88ae3c7d0bbd7312c8095eff2603910437e292a0b53f46c9378f26144c09a6f5')
        self.assertFalse(hasattr(rules,'available_actions'))


if __name__ == '__main__':
    unittest.main()
