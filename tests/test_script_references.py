"""Check script wiring and optional references against an installed CK3 game."""
import os
import copy
from pathlib import Path
import re
import unittest

from test_event_chains import MOD, SWORDS, VANILLA_EFFECTS, effects, matches, one, parse, state, walk


def definitions(path):
    return {key for key, _, _ in parse(path.read_text(encoding='utf-8-sig'))}


class ScriptReferences(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.events = {}
        for path in (MOD / 'events').glob('*.txt'):
            cls.events.update((key, value) for key, _, value in parse(path.read_text())
                         if key != 'namespace')
        cls.on_actions = parse((MOD / 'common/on_action/meitou_travel_on_actions.txt').read_text())

    def test_every_mod_script_parses(self):
        for path in MOD.rglob('*.txt'):
            with self.subTest(path=path.relative_to(MOD)):
                self.assertTrue(parse(path.read_text(encoding='utf-8-sig')))

    def test_story_portraits_have_valid_scopes(self):
        for n, (sword, _, _, _) in enumerate(SWORDS, 1):
            for offset in (0, 100, 200, 300):
                event_id = f'meitou_travel.{offset+n:04}'
                with self.subTest(event=event_id):
                    event = self.events[event_id]
                    self.assertEqual(one(event, 'type'), 'character_event')
                    self.assertEqual(one(event, 'theme'), 'travel')
                    self.assertTrue(one(one(event, 'override_background'), 'reference'))
                    portrait = one(event, 'left_portrait')
                    self.assertEqual(one(portrait, 'character'), 'root')
                    self.assertTrue(one(portrait, 'animation'))
                    other = one(event, 'right_portrait')
                    self.assertEqual(one(other, 'character'),
                                     f'scope:meitou_{sword}_guardian')
                    self.assertTrue(one(other, 'animation'))

    def test_guardian_is_reused_and_direct_previews_create_one(self):
        for n, (sword, _, _, _) in enumerate(SWORDS, 1):
            scope = f'meitou_{sword}_guardian'
            active = state()
            for offset in (0, 100, 200, 300):
                event_id = f'meitou_travel.{offset+n:04}'
                immediate = one(self.events[event_id], 'immediate')
                with self.subTest(event=event_id):
                    created, = effects(immediate, active)
                    self.assertIs(created, active)
                    self.assertEqual(active['created_characters'], [scope])
                    self.assertIn(scope, active['scopes'])
                    fresh = state()
                    effects(immediate, fresh)
                    self.assertEqual(fresh['created_characters'], [scope])
                    creation = one(one(immediate, 'if'), 'create_character')
                    flags = [value for key, _, value in one(creation, 'after_creation')
                             if key == 'add_character_flag']
                    self.assertIn([('flag', '=', 'silently_disappear_me'),
                                   ('years', '=', '1')], flags)

    def test_guardian_is_removed_when_story_ends(self):
        for n, (sword, _, _, _) in enumerate(SWORDS, 1):
            scope = f'meitou_{sword}_guardian'
            for offset, exit_name in ((0, 'meitou_travel.leave'),
                                      (100, 'meitou_travel.withdraw')):
                event = self.events[f'meitou_travel.{offset+n:04}']
                active = state()
                effects(one(event, 'immediate'), active)
                options = [value for key, _, value in event if key == 'option'
                           and one(value, 'name') == exit_name]
                self.assertEqual(len(options), 1)
                effects(options[0], active)
                self.assertNotIn(scope, active['scopes'])
            for offset in (200, 300):
                event = self.events[f'meitou_travel.{offset+n:04}']
                active = state()
                effects(one(event, 'immediate'), active)
                effects(one(event, 'after'), active)
                self.assertNotIn(scope, active['scopes'])
        stale = self.events['meitou_travel.0999']
        for sword, _, _, _ in SWORDS:
            active = state()
            active['scopes'][f'meitou_{sword}_guardian'] = 'character'
            effects(one(stale, 'after'), active)
            self.assertFalse(active['scopes'])

    def test_discovery_draws_all_swords_at_documented_rate(self):
        hook = one(self.on_actions, 'on_travel_plan_movement')
        self.assertIn('meitou_japan_discovery_on_action',
                      [key for key, _, _ in one(hook, 'on_actions')])
        action = one(self.on_actions, 'meitou_japan_discovery_on_action')
        trigger = one(action, 'trigger')
        self.assertTrue(matches(trigger, state()))
        for field, value in [('is_ai', True),
                             ('is_available_travelling_adult', False),
                             ('region', 'elsewhere')]:
            candidate = state()
            candidate[field] = value
            self.assertFalse(matches(trigger, candidate))

        branches = [value for key, _, value in one(action, 'effect')
                    if key == 'if' and any(inner == 'random' for inner, _, _ in value)]
        self.assertEqual(len(branches), len(SWORDS))
        for n, (sword, _, _, _) in enumerate(SWORDS, 1):
            with self.subTest(sword=sword):
                branch = branches[n-1]
                limit = one(branch, 'limit')
                self.assertTrue(matches(limit, state()))
                for blocked in ('found', 'flags'):
                    candidate = state()
                    if blocked == 'found':
                        candidate['found'].add(f'meitou_{sword}_found')
                    else:
                        candidate['flags'][f'meitou_{sword}_recent_encounter'] = 180
                    self.assertFalse(matches(limit, candidate))
                draw = one(branch, 'random')
                self.assertEqual(float(one(draw, 'chance')), 0.5)
                self.assertEqual(one(one(draw, 'trigger_event'), 'id'),
                                 f'meitou_travel.{n:04}')

    def test_vanilla_swords_cannot_duplicate_in_later_starts(self):
        start_hook = one(self.on_actions, 'on_game_start')
        self.assertIn('meitou_record_early_campaign_on_action',
                      [key for key, _, _ in one(start_hook, 'on_actions')])
        start_effect = one(one(self.on_actions, 'meitou_record_early_campaign_on_action'), 'effect')
        early = state()
        effects(start_effect, early)
        self.assertIn('meitou_early_campaign', early['found'])
        early['date'] = (1200, 1, 1)
        late = state()
        late['date'] = (1066, 9, 15)
        effects(start_effect, late)
        self.assertNotIn('meitou_early_campaign', late['found'])
        later = state()
        later['date'] = (1178, 10, 1)
        effects(start_effect, later)
        self.assertNotIn('meitou_early_campaign', later['found'])

        for n, (sword, _, _, _) in enumerate(SWORDS[:4], 1):
            intro = self.events[f'meitou_travel.{n:04}']
            trial = self.events[f'meitou_travel.{100+n:04}']
            self.assertTrue(matches(one(intro, 'trigger'), early))
            self.assertFalse(matches(one(intro, 'trigger'), late))
            self.assertFalse(matches(one(intro, 'trigger'), later))
            options = [value for key, _, value in trial if key == 'option']
            for option in options[:3] + options[5:7]:
                self.assertFalse(matches(one(option, 'trigger'), late))
                bypassed_state = copy.deepcopy(late)
                bypassed_state['gold'] = 100
                for skill in ('prowess', 'learning', 'martial', 'intrigue', 'diplomacy', 'stewardship'):
                    bypassed_state[skill] = 30
                bypassed, = effects(option, bypassed_state)
                self.assertFalse(bypassed['artifacts'])
            unavailable = options[4]
            self.assertTrue(matches(one(unavailable, 'trigger'), late))
            effect_names = {key for key, _, _ in walk(trial)}
            self.assertIn(next(key for key, value in VANILLA_EFFECTS.items()
                               if value == sword), effect_names)
            self.assertNotIn(f'meitou_create_{sword}_effect', effect_names)

    def test_odenta_is_only_mod_generated_in_pre_1178_campaigns(self):
        start_effect = one(one(self.on_actions, 'meitou_record_early_campaign_on_action'), 'effect')
        early = state()
        early['date'] = (1066, 9, 15)
        effects(start_effect, early)
        self.assertIn('meitou_odenta_unseeded_campaign', early['found'])
        early['date'] = (1200, 1, 1)
        late = state()
        late['date'] = (1178, 10, 1)
        effects(start_effect, late)
        self.assertNotIn('meitou_odenta_unseeded_campaign', late['found'])
        intro = self.events['meitou_travel.0006']
        self.assertTrue(matches(one(intro, 'trigger'), early))
        self.assertFalse(matches(one(intro, 'trigger'), late))
        trial = self.events['meitou_travel.0106']
        self.assertIn('create_artifact_odenta_sword_effect',
                      {key for key, _, _ in walk(trial)})
        options = [value for key, _, value in trial if key == 'option']
        for option in options[:3] + options[5:7]:
            bypassed = copy.deepcopy(late)
            bypassed['gold'] = 100
            bypassed['learning'] = 30
            bypassed['diplomacy'] = 30
            self.assertFalse(matches(one(option, 'trigger'), bypassed))
            for result in effects(option, bypassed):
                self.assertFalse(result['artifacts'])

    def test_vanilla_effect_definitions_exist_in_installed_game(self):
        game = Path(os.environ.get('CK3_GAME_DIR',
                       Path.home() / '.local/share/Steam/steamapps/common/Crusader Kings III/game'))
        path = game / 'common/scripted_effects/01_exp1_historical_artifacts_creation_effect.txt'
        if not path.is_file():
            self.skipTest('CK3 game files unavailable')
        effects_defined = set(re.findall(r'^([\w]+)\s*=\s*\{', path.read_text(), re.M))
        self.assertTrue(VANILLA_EFFECTS.keys() <= effects_defined)

    def test_artifact_references_resolve_within_mod(self):
        effects = parse((MOD / 'common/scripted_effects/meitou_artifact_effects.txt').read_text())
        visuals = definitions(MOD / 'common/artifacts/visuals/meitou_visuals.txt')
        modifiers = definitions(MOD / 'common/modifiers/meitou_modifiers.txt')
        localization = set()
        for path in (MOD / 'localization/english').glob('*.yml'):
            localization.update(re.findall(r'^ ([\w.]+):0 ',
                                           path.read_text(encoding='utf-8-sig'), re.M))
        for sword, _, _, _ in SWORDS:
            with self.subTest(sword=sword):
                if sword == 'odenta':
                    continue  # Vanilla provides this sword's complete creation effect.
                effect = one(effects, f'meitou_create_{sword}_effect')
                artifact = one(effect, 'create_artifact')
                self.assertEqual(one(artifact, 'type'), 'sword')
                self.assertEqual(one(artifact, 'decaying'), 'no')
                self.assertIn(one(artifact, 'visuals'), visuals)
                self.assertIn(one(artifact, 'modifier'), modifiers)
                self.assertIn(one(artifact, 'name'), localization)
                self.assertIn(one(artifact, 'description'), localization)

    def test_upgrade_targets_named_swords_even_after_repeated_upgrades(self):
        triggers = parse((MOD / 'common/scripted_triggers/meitou_start_triggers.txt').read_text())
        eligible = one(triggers, 'meitou_upgrade_eligible_artifact_trigger')
        base_modifiers = {value for key, _, value in one(eligible, 'OR')
                          if key == 'has_artifact_modifier'}
        self.assertEqual(base_modifiers, {
            'higekiri_sword_modifier', 'hizamaru_sword_modifier',
            'mikazuki_munechika_sword_modifier', 'dojigiri_sword_modifier',
            'odenta_sword_modifier',
            *{f'meitou_{sword}_modifier' for sword, *_ in SWORDS if sword != 'odenta'},
        })
        for base in base_modifiers:
            for upgrades in (0, 1, 2, 100):
                with self.subTest(base=base, upgrades=upgrades):
                    artifact = {'artifact_modifiers': [base] +
                                ['meitou_honed_blade_modifier'] * upgrades}
                    self.assertTrue(matches(eligible, artifact))
        for modifiers in ([], ['meitou_honed_blade_modifier'], ['unrelated_modifier']):
            self.assertFalse(matches(eligible, {'artifact_modifiers': modifiers}))
        modifiers = parse((MOD / 'common/modifiers/meitou_modifiers.txt').read_text())
        self.assertEqual(one(one(modifiers, 'meitou_honed_blade_modifier'),
                             'prowess_no_portrait'), '1')

    def test_upgrade_event_uses_owned_artifact_and_one_payment(self):
        self.assertNotIn('on_yearly_events', definitions(MOD / 'common/on_action/meitou_travel_on_actions.txt'))
        movement = one(self.on_actions, 'on_travel_plan_movement')
        self.assertIn('meitou_swordsmith_visit_on_action',
                      [key for key, _, _ in one(movement, 'on_actions')])
        pulse = one(self.on_actions, 'meitou_swordsmith_visit_on_action')
        self.assertEqual(one(one(one(pulse, 'effect'), 'random'), 'chance'), '10')
        self.assertEqual(one(one(pulse, 'trigger'), 'meitou_swordsmith_destination_trigger'), 'yes')
        self.assertEqual(one(one(one(pulse, 'trigger'), 'NOT'), 'has_character_flag'),
                         'meitou_upgrade_recent_encounter')
        event = self.events['meitou_upgrade.0001']
        self.assertEqual(one(one(event, 'trigger'), 'meitou_swordsmith_destination_trigger'), 'yes')
        self.assertEqual(one(one(one(event, 'immediate'), 'add_character_flag'), 'days'), '365')
        destinations = one(parse((MOD / 'common/scripted_triggers/meitou_start_triggers.txt').read_text()),
                           'meitou_swordsmith_destination_trigger')
        self.assertEqual({value for key, _, value in one(destinations, 'OR') if key == 'location'},
                         {'province:10603', 'province:10587', 'province:10583', 'province:10533'})
        desc = one(one(event, 'desc'), 'first_valid')
        location_descs = [value for key, _, value in desc if key == 'triggered_desc'
                          and any(k == 'trigger' for k, _, _ in value)]
        self.assertEqual({one(one(item, 'trigger'), 'location') for item in location_descs},
                         {'province:10603', 'province:10587', 'province:10583', 'province:10533'})
        self.assertEqual(one(one(one(event, 'immediate'), 'random_character_artifact'),
                             'save_scope_as'), 'meitou_upgrade_target')
        options = {one(value, 'name'): value for key, _, value in event if key == 'option'}
        self.assertEqual(set(options), {'meitou_upgrade.0001.a',
                                        'meitou_upgrade.0001.b',
                                        'meitou_upgrade.0001.c'})
        paid = options['meitou_upgrade.0001.a']
        self.assertEqual(one(one(paid, 'if'), 'remove_short_term_gold'), '70')
        for name in ('meitou_upgrade.0001.a', 'meitou_upgrade.0001.b'):
            guard = one(one(options[name], 'if'), 'limit')
            artifact = one(guard, 'scope:meitou_upgrade_target')
            self.assertEqual(one(artifact, 'artifact_owner'), 'root')
            self.assertEqual(one(artifact, 'meitou_upgrade_eligible_artifact_trigger'), 'yes')
            self.assertTrue(any(key == 'add_artifact_modifier' and value == 'meitou_honed_blade_modifier'
                                for key, _, value in walk(options[name])))
        self.assertFalse(any(key in ('add_artifact_modifier', 'remove_short_term_gold')
                             for key, _, _ in walk(options['meitou_upgrade.0001.c'])))

    def test_swordsmith_destinations_match_installed_japan_baronies(self):
        game = Path(os.environ.get('CK3_GAME_DIR',
                    Path.home() / '.local/share/Steam/steamapps/common/Crusader Kings III/game'))
        titles = game / 'common/landed_titles/01_japan.txt'
        if not titles.is_file():
            self.skipTest('CK3 Japan landed titles unavailable')
        text = titles.read_text()
        for barony, province in {'b_kyo': 10603, 'b_oku': 10587,
                                 'b_kuboya': 10583, 'b_mii': 10533}.items():
            with self.subTest(barony=barony):
                self.assertRegex(text, rf'\b{barony}\s*=\s*\{{\s*province\s*=\s*{province}\b')

    def test_story_art_references_exist_in_installed_game(self):
        game = Path(os.environ.get('CK3_GAME_DIR',
                       Path.home() / '.local/share/Steam/steamapps/common/Crusader Kings III/game'))
        backgrounds = game / 'common/event_backgrounds/01_event_backgrounds.txt'
        animations = game / 'gfx/portraits/portrait_animations/animations.txt'
        travel_hooks = game / 'common/on_action/travel_on_actions.txt'
        if not all(path.is_file() for path in (backgrounds, animations, travel_hooks)):
            self.skipTest('CK3 game files unavailable; set CK3_GAME_DIR to validate assets')
        self.assertIn('on_travel_plan_movement', definitions(travel_hooks))
        background_ids = set(re.findall(r'^([\w]+)\s*=\s*\{', backgrounds.read_text(), re.M))
        animation_ids = set(re.findall(r'^([\w]+)\s*=\s*\{', animations.read_text(), re.M))
        for n, _ in enumerate(SWORDS, 1):
            for offset in (0, 100, 200, 300):
                event_id = f'meitou_travel.{offset+n:04}'
                with self.subTest(event=event_id):
                    event = self.events[event_id]
                    self.assertIn(one(one(event, 'override_background'), 'reference'), background_ids)
                    self.assertIn(one(one(event, 'left_portrait'), 'animation'), animation_ids)
                    self.assertIn(one(one(event, 'right_portrait'), 'animation'), animation_ids)

        templates = game / 'common/scripted_character_templates/00_pool_repopulation_character_templates.txt'
        self.assertTrue(templates.is_file())
        template_ids = set(re.findall(r'^([\w]+)\s*=\s*\{', templates.read_text(), re.M))
        for n, _ in enumerate(SWORDS, 1):
            creation = one(one(one(self.events[f'meitou_travel.{n:04}'], 'immediate'),
                               'if'), 'create_character')
            self.assertIn(one(creation, 'template'), template_ids)

        visuals = parse((MOD / 'common/artifacts/visuals/meitou_visuals.txt').read_text())
        asset_dir = game / 'gfx/models/artifacts/props'
        asset_names = set()
        for path in asset_dir.rglob('*.asset'):
            asset_names.update(re.findall(r'\bname\s*=\s*"([\w]+)"', path.read_text()))
        for key, _, visual in visuals:
            with self.subTest(visual=key):
                icon = one(visual, 'icon').strip('"')
                self.assertTrue(any((root / 'gfx/interface/icons/artifact' / icon).is_file()
                                    for root in (MOD, game)), icon)
                self.assertIn(one(visual, 'asset'), asset_names)


if __name__ == '__main__':
    unittest.main()
