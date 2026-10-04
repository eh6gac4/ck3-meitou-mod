"""Check debug controls without claiming to execute the CK3 engine."""
import copy
import unittest
import test_event_chains as chains
from test_event_chains import MOD, SWORDS, parse, one, walk, matches, effects, state


class DebugMenu(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        chains.EventChains.setUpClass()
        cls.events = chains.EventChains.events
        cls.decision = one(parse((MOD / 'common/decisions/meitou_debug_decisions.txt').read_text()), 'meitou_debug_decision')

    def options(self, event):
        return {one(v, 'name'): v for k, _, v in self.events[event] if k == 'option'}

    def test_debug_gates_and_decision_references(self):
        for ai in (False, True):
            for debug in (False, True):
                s = state()
                s.update(is_ai=ai, debug_only=debug)
                expected = debug and not ai
                for key in ('is_shown', 'is_valid'):
                    self.assertEqual(matches(one(self.decision, key), s), expected)
                for name, event in self.events.items():
                    if name.startswith('meitou_debug.'):
                        self.assertEqual(matches(one(event, 'trigger'), s), expected)
        self.assertEqual(one(one(self.decision, 'effect'), 'trigger_event'), [('id', '=', 'meitou_debug.0001')])
        self.assertEqual(one(self.decision, 'ai_check_interval'), '0')
        self.assertEqual(one(one(self.decision, 'ai_will_do'), 'base'), '0')
        keys = set()
        import re
        for path in (MOD / 'localization/english').glob('*.yml'):
            keys.update(re.findall(r'^ ([\w.]+):', path.read_text(encoding='utf-8-sig'), re.M))
        self.assertIn('meitou_debug_decision', keys)
        for key in ('desc', 'selection_tooltip', 'confirm_text'):
            self.assertIn(one(self.decision, key), keys)

    def test_intro_bypass_is_one_use_and_does_not_bypass_uniqueness(self):
        for n, (sword, _, _, _) in enumerate(SWORDS, 1):
            option = self.options(f'meitou_debug.{100+n:04}')['meitou_debug.intro']
            intro = self.events[f'meitou_travel.{n:04}']
            s = state()
            s.update(debug_only=True, region='elsewhere', is_available_travelling_adult=False)
            s['flags'][f'meitou_{sword}_recent_encounter'] = 180
            self.assertFalse(matches(one(intro, 'trigger'), s))
            result, = effects(option, s)
            self.assertEqual(result['events'], [f'meitou_travel.{n:04}'])
            self.assertTrue(matches(one(intro, 'trigger'), result))
            off = copy.deepcopy(result)
            off['debug_only'] = False
            self.assertFalse(matches(one(intro, 'trigger'), off))
            claimed = copy.deepcopy(result)
            claimed['found'].add(f'meitou_{sword}_found')
            self.assertFalse(matches(one(intro, 'trigger'), claimed))
            self.assertFalse(matches(one(option, 'trigger'), claimed))
            effects(one(intro, 'immediate'), result)
            self.assertNotIn(f'meitou_debug_{sword}_intro', result['flags'])
            self.assertFalse(matches(one(intro, 'trigger'), result))

    def test_preview_and_trial_links(self):
        main = self.options('meitou_debug.0001')
        for n, (sword, _, _, _) in enumerate(SWORDS, 1):
            chosen, = effects(main[f'meitou_debug.choose_{sword}'], state())
            self.assertEqual(chosen['events'], [f'meitou_debug.{100+n:04}'])
            menu = self.options(chosen['events'][0])
            for label, offset in [('trial', 100), ('success_preview', 200), ('failure_preview', 300)]:
                result, = effects(menu['meitou_debug.'+label], state())
                self.assertEqual(result['events'], [f'meitou_travel.{offset+n:04}'])
                self.assertFalse(result['found'] or result['artifacts'])
                self.assertEqual((result['gold'], result['stress']), (0, 0))
                if 'preview' in label:
                    terminal = self.options(result['events'][0])
                    effects(next(iter(terminal.values())), result)
                    self.assertFalse(result['found'] or result['artifacts'])
            reset_link, = effects(menu['meitou_debug.reset'], state())
            self.assertFalse(reset_link['found'] or reset_link['artifacts'])
            self.assertEqual(reset_link['events'], [f'meitou_debug.{200+n:04}'])

    def test_forced_outcomes_and_disabled_mode(self):
        for n, (sword, _, stress, _) in enumerate(SWORDS, 1):
            opts = self.options(f'meitou_travel.{100+n:04}')
            for outcome in ('success', 'failure'):
                option = opts['meitou_debug.force_'+outcome]
                for debug, ai, claimed in [(False, False, False), (True, True, False), (True, False, True)]:
                    s = state()
                    s.update(debug_only=debug, is_ai=ai)
                    if claimed: s['found'].add(f'meitou_{sword}_found')
                    self.assertFalse(matches(one(option, 'trigger'), s))
                    before = copy.deepcopy(s)
                    result, = effects(option, s)
                    for field in ('gold', 'stress', 'artifacts', 'found', 'events'):
                        self.assertEqual(result[field], before[field])
                s = state()
                s['debug_only'] = True
                self.assertTrue(matches(one(option, 'trigger'), s))
                result, = effects(option, s)
                self.assertEqual(result['gold'], 0)
                self.assertEqual(result['probability'], 1)
                if outcome == 'success':
                    self.assertEqual(result['artifacts'], [sword])
                    self.assertEqual(result['found'], {f'meitou_{sword}_found'})
                    self.assertEqual(result['stress'], 0)
                    self.assertEqual(result['events'], [f'meitou_travel.{200+n:04}'])
                else:
                    self.assertFalse(result['artifacts'] or result['found'])
                    self.assertEqual(result['stress'], stress)
                    self.assertEqual(result['events'], [f'meitou_travel.{300+n:04}'])

    def test_reset_is_explicit_and_preserves_artifacts_and_other_swords(self):
        for n, (sword, _, _, _) in enumerate(SWORDS, 1):
            options = self.options(f'meitou_debug.{200+n:04}')
            s = state(gold=250, skill=12)
            s['debug_only'] = True
            s['stress'] = 30
            s['artifacts'] = [item[0] for item in SWORDS]
            s['found'] = {f'meitou_{item[0]}_found' for item in SWORDS}
            s['flags'] = {f'meitou_{item[0]}_recent_encounter': 180 for item in SWORDS}
            s['flags'][f'meitou_debug_{sword}_intro'] = 1
            canceled, = effects(options['meitou_debug.cancel'], copy.deepcopy(s))
            for field in ('gold','stress','artifacts','found','flags'):
                self.assertEqual(canceled[field], s[field])
            result, = effects(options['meitou_debug.reset_confirm'], copy.deepcopy(s))
            self.assertEqual(result['found'], s['found'])
            self.assertNotIn(f'meitou_{sword}_recent_encounter', result['flags'])
            self.assertNotIn(f'meitou_debug_{sword}_intro', result['flags'])
            self.assertEqual(len(result['flags']), len(SWORDS) - 1)
            for field in ('gold','stress','artifacts','learning','martial'):
                self.assertEqual(result[field], s[field])


if __name__ == '__main__':
    unittest.main()
