"""Balance totals and guarded upgrade outcomes; this does not run the CK3 engine."""
import copy
from pathlib import Path
import os
import re
import unittest

from test_event_chains import MOD, SCRIPTED_EFFECTS, effects, matches, one, parse, state

TOTALS = {
    'higekiri': {'prowess_no_portrait': [7,8,9,10], 'dread_baseline_add': [10,12,15,20], 'dread_decay_mult': [-.15,-.20,-.25,-.30]},
    'hizamaru': {'prowess_no_portrait': [6,7,8,9], 'martial': [1,1,2,3], 'monthly_county_control_growth_factor': [.15,.20,.25,.30]},
    'mikazuki': {'prowess_no_portrait': [6,7,8,9], 'diplomacy': [1,2,2,3], 'vassal_opinion': [5,5,10,15]},
    'dojigiri': {'prowess_no_portrait': [8,9,10,12], 'knight_effectiveness_mult': [.10,.15,.18,.20]},
    'ookanehira': {'prowess_no_portrait': [10,11,13,15], 'knight_effectiveness_mult': [.05,.08,.10,.15]},
    'odenta': {'prowess_no_portrait': [7,8,9,10], 'vassal_opinion': [5,10,10,15], 'monthly_prestige': [.7,.9,1.1,1.3]},
    'juzumaru': {'prowess_no_portrait': [6,7,8,9], 'learning': [2,2,3,3], 'monthly_piety': [.3,.4,.6,.8]},
    'onimaru': {'prowess_no_portrait': [8,9,10,12], 'intrigue': [1,2,2,3], 'dread_baseline_add': [10,15,20,25]},
}
VANILLA = {
    'higekiri': ('higekiri_sword_modifier', {'prowess_no_portrait':2, 'monthly_prestige':.2, 'dread_decay_mult':-.15}),
    'hizamaru': ('hizamaru_sword_modifier', {'prowess_no_portrait':2, 'monthly_prestige':.2, 'monthly_county_control_growth_factor':.15}),
    'mikazuki': ('mikazuki_munechika_sword_modifier', {'prowess_no_portrait':2, 'monthly_prestige':.2, 'knight_effectiveness_mult':.1}),
    'dojigiri': ('dojigiri_sword_modifier', {'prowess_no_portrait':2, 'monthly_prestige':.2, 'monthly_dynasty_prestige_mult':.05}),
    'odenta': ('odenta_sword_modifier', {'prowess_no_portrait':2, 'monthly_prestige':.2, 'fellow_vassal_opinion':10, 'vassal_opinion':5}),
}


def blade(sword, vanilla=False, owner='root'):
    base = VANILLA[sword][0] if vanilla else f'meitou_{sword}_modifier'
    return {'artifact_modifiers': [base], 'artifact_owner': owner}


def apply(name, artifact):
    return effects(SCRIPTED_EFFECTS[name], artifact)[0]


class SwordBalance(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.modifiers = {key: {k:float(v) for k, _, v in value}
                         for key, _, value in parse((MOD/'common/modifiers/meitou_modifiers.txt').read_text())}
        cls.modifiers.update({name: stats for name, stats in VANILLA.values()})
        events = parse((MOD/'events/meitou_upgrade_events.txt').read_text())
        event = one(events, 'meitou_upgrade.0001')
        cls.options = {one(value,'name'):value for key, _, value in event if key=='option'}

    def test_all_totals_and_cap_for_vanilla_and_legacy_blades(self):
        for sword in TOTALS:
            sources = [False] if sword not in VANILLA else [True] if sword=='odenta' else [False, True]
            for vanilla in sources:
                art = blade(sword, vanilla)
                apply('meitou_prepare_sword_effect', art)
                original = copy.deepcopy(art)
                apply('meitou_prepare_sword_effect', art)
                self.assertEqual(art, original, 'Base bonus must be idempotent')
                for level in range(4):
                    with self.subTest(sword=sword, vanilla=vanilla, level=level):
                        expected = {k: values[level] for k, values in TOTALS[sword].items()}
                        expected.setdefault('monthly_prestige', [.5,.6,.7,.8][level])
                        actual = {}
                        for modifier in art['artifact_modifiers']:
                            for key, value in self.modifiers[modifier].items():
                                actual[key] = actual.get(key,0)+value
                        for key in actual.keys() | expected.keys():
                            self.assertAlmostEqual(actual.get(key,0), expected.get(key,0), msg=key)
                        self.assertEqual(matches([('meitou_upgrade_eligible_artifact_trigger','=','yes')],art),level<3)
                    if level<3:
                        apply('meitou_apply_polish_effect',art)
                final = copy.deepcopy(art)
                for _ in range(5):
                    apply('meitou_apply_polish_effect',art)
                self.assertEqual(art,final,'Completed swords must not grow or stack modifiers')

    def test_legacy_upgrade_migration_is_capped_and_idempotent(self):
        for sword in TOTALS:
            for old_count in (0,1,2,3,4,100):
                with self.subTest(sword=sword, count=old_count):
                    art = blade(sword,sword=='odenta')
                    art['artifact_modifiers'] += ['meitou_honed_blade_modifier']*old_count
                    apply('meitou_migrate_polish_effect',art)
                    self.assertNotIn('meitou_honed_blade_modifier',art['artifact_modifiers'])
                    expected_level = min(old_count,3)
                    stages = [m for m in art['artifact_modifiers'] if '_polish_' in m]
                    self.assertEqual(stages,[f'meitou_{sword}_polish_{expected_level}_modifier'] if expected_level else [])
                    saved = copy.deepcopy(art)
                    apply('meitou_migrate_polish_effect',art)
                    self.assertEqual(art,saved)

    def actor(self, level=0, gold=0, prowess=0, owner='root'):
        active=state(skill=prowess,gold=gold)
        art=blade('dojigiri',True,owner)
        apply('meitou_prepare_sword_effect',art)
        for _ in range(level):
            apply('meitou_apply_polish_effect',art)
        active['scopes']['meitou_upgrade_target']=art
        return active

    def test_payment_boundaries_and_stale_choices_for_each_stage(self):
        for level,cost in enumerate((70,120,200)):
            option=self.options[f'meitou_upgrade.0001.a{level+1}']
            for funds in (cost-1,cost,cost+1):
                with self.subTest(level=level,funds=funds):
                    active=self.actor(level,funds)
                    self.assertEqual(matches(one(option,'trigger'),active),funds>=cost)
                    before=copy.deepcopy(active['scopes']['meitou_upgrade_target'])
                    result,=effects(option,active)
                    self.assertEqual(result['gold'],funds-cost if funds>=cost else funds)
                    self.assertEqual(result['events'],['meitou_upgrade.0002' if funds>=cost else 'meitou_upgrade.0004'])
                    if funds>=cost:
                        self.assertIn(f'meitou_dojigiri_polish_{level+1}_modifier',result['scopes']['meitou_upgrade_target']['artifact_modifiers'])
                    else:
                        self.assertEqual(result['scopes']['meitou_upgrade_target'],before)
            for stale in (self.actor(level,cost,owner='other'),self.actor(3,cost),state(gold=cost)):
                before=copy.deepcopy(stale)
                result,=effects(option,stale)
                self.assertEqual(result['gold'],cost)
                self.assertEqual(result['scopes'],before['scopes'])
                self.assertEqual(result['events'],['meitou_upgrade.0004'])
        # A stale cheap option cannot charge 70 gold for stage II.
        active=self.actor(1,200)
        before=copy.deepcopy(active['scopes'])
        result,=effects(self.options['meitou_upgrade.0001.a1'],active)
        self.assertEqual(result['gold'],200)
        self.assertEqual(result['scopes'],before)

    def test_self_polishing_success_failure_and_completed_guard(self):
        option=self.options['meitou_upgrade.0001.b']
        for level in range(3):
            for prowess,chance in [(11,.4),(12,.7)]:
                active=self.actor(level,prowess=prowess)
                results=effects(option,active)
                self.assertEqual(len(results),2)
                success=next(r for r in results if r['events']==['meitou_upgrade.0002'])
                failure=next(r for r in results if r['events']==['meitou_upgrade.0003'])
                self.assertAlmostEqual(success['probability'],chance)
                self.assertEqual(success['gold'],0)
                self.assertEqual(success['stress'],0)
                self.assertIn(f'meitou_dojigiri_polish_{level+1}_modifier',success['scopes']['meitou_upgrade_target']['artifact_modifiers'])
                self.assertEqual(failure['stress'],10)
                self.assertEqual(failure['scopes'],active['scopes'])
        for active in (self.actor(3),self.actor(owner='other')):
            saved=copy.deepcopy(active['scopes'])
            result,=effects(option,active)
            self.assertEqual(result['events'],['meitou_upgrade.0004'])
            self.assertEqual(result['stress'],0)
            self.assertEqual(result['scopes'],saved)

    def test_vanilla_baselines_match_installed_game(self):
        game=Path(os.environ.get('CK3_GAME_DIR',Path.home()/'.local/share/Steam/steamapps/common/Crusader Kings III/game'))
        path=game/'common/modifiers/00_historical_artifact_modifiers.txt'
        if not path.is_file():
            self.skipTest('CK3 game files unavailable')
        text=path.read_text(encoding='utf-8-sig')
        for name, expected in VANILLA.values():
            block=re.search(r'^'+name+r'\s*=\s*\{([^}]+)\}',text,re.M)[1]
            actual={k:float(v) for k, _, v in parse(block)}
            self.assertEqual(actual,expected)
