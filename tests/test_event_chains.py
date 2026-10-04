"""Static structure and restricted effect simulation, NOT a CK3 engine test.
Run: python -m unittest discover -s tests -v
"""
from pathlib import Path
import copy
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]
MOD = ROOT / 'meitou_mod'
SWORDS = [('higekiri', 45, 25, ('prowess', 'diplomacy')),
          ('hizamaru', 40, 20, ('learning', 'diplomacy')),
          ('mikazuki', 80, 15, ('learning', 'diplomacy')),
          ('dojigiri', 60, 30, ('martial', 'intrigue')),
          ('ookanehira', 60, 20, ('stewardship', 'martial')),
          ('odenta', 80, 20, ('learning', 'diplomacy')),
          ('juzumaru', 70, 15, ('learning', 'diplomacy')),
          ('onimaru', 70, 25, ('martial', 'intrigue'))]
VANILLA_EFFECTS = {
    'create_artifact_higekiri_sword_effect': 'higekiri',
    'create_artifact_hizamaru_sword_effect': 'hizamaru',
    'create_artifact_mikazuki_munechika_sword_effect': 'mikazuki',
    'create_artifact_dojigiri_sword_effect': 'dojigiri',
    'create_artifact_odenta_sword_effect': 'odenta',
}


def parse(text):
    token = re.compile(r'\s+|#[^\n]*|"(?:\\.|[^"\\])*"|>=|<=|[{}=<>]|[^\s{}=<>"#]+')
    tokens = []
    pos = 0
    for m in token.finditer(text):
        if m.start() != pos:
            raise ValueError(f'Unparsed text at {pos}')
        pos = m.end()
        if not m[0].isspace() and not m[0].startswith('#'):
            tokens.append(m[0])
    if pos != len(text):
        raise ValueError('Trailing unparsed text')
    i = 0

    def block(nested=False):
        nonlocal i
        out = []
        while i < len(tokens):
            if tokens[i] == '}':
                if not nested:
                    raise ValueError('Unexpected closing brace')
                i += 1
                return out
            key = tokens[i]
            i += 1
            if i < len(tokens) and tokens[i] not in ('=', '>=', '<=', '>', '<'):
                out.append((key, '', None))  # Bare items in on_actions lists.
                continue
            op = tokens[i]
            i += 1
            if op not in ('=', '>=', '<=', '>', '<'):
                raise ValueError(f'Invalid operator: {op}')
            value = tokens[i]
            i += 1
            if value == '{':
                value = block(True)
            out.append((key, op, value))
        if nested:
            raise ValueError('Unclosed block')
        return out

    return block()


def one(block, key):
    values = [v for k, _, v in block if k == key]
    if len(values) != 1:
        raise AssertionError(f'{key}: expected one, got {len(values)}')
    return values[0]


SCRIPTED_TRIGGERS = {
    key: value for key, _, value in parse((MOD / 'common/scripted_triggers/meitou_start_triggers.txt').read_text())
}


def walk(block):
    for k, op, v in block:
        yield k, op, v
        if isinstance(v, list):
            yield from walk(v)


def matches(block, state):
    for key, op, value in block:
        if key in SCRIPTED_TRIGGERS:
            result = matches(SCRIPTED_TRIGGERS[key], state) == (value == 'yes')
        elif key == 'OR':
            result = any(matches([entry], state) for entry in value)
        elif key == 'AND':
            result = matches(value, state)
        elif key == 'NOT':
            result = not matches(value, state)
        elif key == 'has_global_variable':
            result = value in state['found']
        elif key == 'has_character_flag':
            result = value in state['flags']
        elif key == 'exists':
            if not value.startswith('scope:'):
                raise AssertionError(f'Unknown scope reference: {value}')
            result = value[6:] in state['scopes']
        elif key == 'location':
            result = matches(value, state)
        elif key == 'geographical_region':
            result = state['region'] == value
        elif key == 'current_date':
            date = tuple(int(part) for part in value.split('.'))
            if op == '<':
                result = state['date'] < date
            else:
                raise AssertionError(f'Unknown date comparison: {op}')
        elif key in ('is_ai', 'is_available_travelling_adult', 'debug_only'):
            result = state[key] == (value == 'yes')
        elif key in ('gold', 'prowess', 'learning', 'martial', 'intrigue', 'diplomacy', 'stewardship'):
            if op != '>=':
                raise AssertionError(op)
            result = state[key] >= float(value)
        else:
            raise AssertionError(f'Unknown trigger: {key}')
        if not result:
            return False
    return True


def effects(block, state):
    """Explore every weighted outcome; each result has its exact probability."""
    states = [state]
    previous_if = None
    for key, op, value in block:
        if key in ('name', 'trigger', 'limit'):
            continue
        if key == 'if':
            condition = one(value, 'limit')
            for s in states:
                s['_last_if'] = matches(condition, s)
            yes = [s for s in states if s['_last_if']]
            no = [s for s in states if not s['_last_if']]
            # Preserve the outer decision across nested if/else blocks.
            next_states = []
            for s in yes:
                for out in effects(value, s):
                    out['_last_if'] = True
                    next_states.append(out)
            states = next_states + no
            previous_if = True
        elif key == 'else':
            if previous_if is None:
                raise AssertionError('else without if')
            next_states = []
            for s in states:
                if s['_last_if']:
                    next_states.append(s)
                else:
                    next_states.extend(effects(value, s))
            states = next_states
            previous_if = None
        elif key == 'random_list':
            total = sum(int(k) for k, _, _ in value)
            next_states = []
            for s in states:
                for weight, _, branch in value:
                    child = copy.deepcopy(s)
                    child['probability'] *= int(weight) / total
                    next_states.extend(effects(branch, child))
            states = next_states
        else:
            for s in states:
                if key == 'add_gold':
                    s['gold'] += int(value)
                elif key == 'remove_short_term_gold':
                    s['gold'] -= int(value)
                elif key == 'add_stress':
                    s['stress'] += int(value)
                elif key == 'remove_character_flag':
                    s['flags'].pop(value, None)
                elif key == 'remove_global_variable':
                    s['found'].discard(value)
                elif key == 'set_global_variable':
                    s['found'].add(value)
                elif key == 'trigger_event':
                    s['events'].append(one(value, 'id'))
                elif key == 'add_character_flag':
                    s['flags'][one(value, 'flag')] = int(one(value, 'days'))
                elif key == 'create_character':
                    scope = one(value, 'save_scope_as')
                    if scope in s['scopes']:
                        raise AssertionError(f'Duplicate character: {scope}')
                    s['scopes'][scope] = one(value, 'template')
                    s['created_characters'].append(scope)
                elif key.startswith('scope:'):
                    if one(value, 'silent_disappearance_effect') != 'yes':
                        raise AssertionError(f'Unknown scoped effect: {key}')
                    s['scopes'].pop(key[6:])
                elif key in VANILLA_EFFECTS:
                    if one(value, 'OWNER') != 'root':
                        raise AssertionError('Wrong recipient')
                    s['artifacts'].append(VANILLA_EFFECTS[key])
                elif re.fullmatch(r'meitou_create_\w+_effect', key):
                    if one(value, 'OWNER') != 'root':
                        raise AssertionError('Wrong recipient')
                    s['artifacts'].append(key[len('meitou_create_'):-len('_effect')])
                else:
                    raise AssertionError(f'Unknown effect: {key}')
    return states


def state(skill=0, gold=0):
    return dict(found=set(), flags={}, scopes={}, created_characters=[],
                events=[], artifacts=[], stress=0,
                probability=1, gold=gold, region='world_asia_japan',
                date=(867, 1, 1),
                is_ai=False, is_available_travelling_adult=True, debug_only=False,
                **{k: skill for k in ['prowess', 'learning', 'martial', 'intrigue', 'diplomacy', 'stewardship']})


class EventChains(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.events = {}
        for path in (MOD / 'events').glob('*.txt'):
            for key, _, val in parse(path.read_text(encoding='utf-8-sig')):
                if key == 'namespace':
                    continue
                if key in cls.events:
                    raise AssertionError(f'Duplicate event: {key}')
                cls.events[key] = val
        cls.on_action = one(parse((MOD / 'common/on_action/meitou_travel_on_actions.txt').read_text()), 'meitou_japan_discovery_on_action')

    def test_graph_and_localization(self):
        self.assertEqual(len(self.events), 2 + 6 * len(SWORDS) + 4)
        languages = []
        for language in ['japanese', 'english']:
            keys = []
            for path in (MOD / 'localization' / language).glob('*.yml'):
                self.assertTrue(path.read_bytes().startswith(b'\xef\xbb\xbf'))
                text = path.read_text(encoding='utf-8-sig')
                self.assertEqual(text.splitlines()[0], 'l_' + language + ':')
                for line in text.splitlines()[1:]:
                    match = re.fullmatch(r' ([\w.]+):0 "(?:\\.|[^"\\])*"', line)
                    self.assertIsNotNone(match, line)
                    keys.append(match[1])
            self.assertEqual(len(keys), len(set(keys)))
            languages.append(set(keys))
        self.assertEqual(*languages)
        for key, block in self.events.items():
            for k, _, val in walk(block):
                if k in ('title', 'desc', 'name'):
                    self.assertIn(val, languages[0])
                if k == 'trigger_event':
                    self.assertIn(one(val, 'id'), self.events)
            self.assertTrue(any(k == 'option' for k, _, _ in block))
        # Every entry reaches its own challenge; success/failure are terminal.
        for n in range(1, len(SWORDS) + 1):
            intro = self.events[f'meitou_travel.{n:04}']
            opts = [v for k, _, v in intro if k == 'option']
            self.assertEqual(one(one(opts[0], 'trigger_event'), 'id'), f'meitou_travel.{100+n:04}')
            for end in (200+n, 300+n):
                self.assertFalse(any(k == 'trigger_event' for k, _, _ in walk(self.events[f'meitou_travel.{end:04}'])))

    def test_eligibility_cooldowns_and_continuations(self):
        for n, (sword, _, _, _) in enumerate(SWORDS, 1):
            intro = self.events[f'meitou_travel.{n:04}']
            s = state()
            self.assertTrue(matches(one(intro, 'trigger'), s))
            effects(one(intro, 'immediate'), s)
            self.assertEqual(s['flags'][f'meitou_{sword}_recent_encounter'], 180)
            self.assertFalse(matches(one(intro, 'trigger'), s))
            s['flags'].clear()  # Simulate timer expiry.
            self.assertTrue(matches(one(intro, 'trigger'), s))
            for field, value in [('is_ai', True), ('is_available_travelling_adult', False), ('region', 'elsewhere')]:
                changed = copy.deepcopy(s)
                changed[field] = value
                self.assertFalse(matches(one(intro, 'trigger'), changed))
            s['found'].add(f'meitou_{sword}_found')
            self.assertFalse(matches(one(intro, 'trigger'), s))
            trial = self.events[f'meitou_travel.{100+n:04}']
            self.assertFalse(any(k == 'trigger' for k, _, _ in trial))
            filters = [one(v, 'limit') for k, _, v in one(self.on_action, 'effect')
                       if k == 'if' and any(inner == 'random' for inner, _, _ in v)]
            self.assertFalse(matches(filters[n-1], s))
            s = state()
            s['flags'][f'meitou_{sword}_recent_encounter'] = 180
            self.assertFalse(matches(filters[n-1], s))

    def test_all_skill_outcomes_and_cost_boundaries(self):
        for n, (sword, cost, stress, skills) in enumerate(SWORDS, 1):
            options = [v for k, _, v in self.events[f'meitou_travel.{100+n:04}'] if k == 'option']
            for index, skill in enumerate(skills):
                for level, expected in [(0, .45), (11, .45), (12, .80), (30, .80)]:
                    with self.subTest(sword=sword, route=index, level=level):
                        s = state()
                        s[skill] = level
                        self.assertTrue(matches(one(options[index], 'trigger'), s))
                        outcomes = effects(options[index], s)
                        self.assertEqual(len(outcomes), 2)
                        self.assertAlmostEqual(sum(o['probability'] for o in outcomes), 1)
                        win = next(o for o in outcomes if o['artifacts'])
                        lose = next(o for o in outcomes if not o['artifacts'])
                        self.assertAlmostEqual(win['probability'], expected)
                        self.assertEqual(win['artifacts'], [sword])
                        self.assertEqual(win['found'], {f'meitou_{sword}_found'})
                        self.assertEqual(win['events'], [f'meitou_travel.{200+n:04}'])
                        self.assertEqual(win['gold'], 0)
                        self.assertEqual(lose['gold'], 0)
                        self.assertEqual(lose['stress'], stress)
                        self.assertFalse(lose['found'])
                        self.assertEqual(lose['events'], [f'meitou_travel.{300+n:04}'])
            self.assertFalse(matches(one(options[2], 'trigger'), state(gold=cost-1)))
            s = state(gold=cost)
            self.assertTrue(matches(one(options[2], 'trigger'), s))
            result, = effects(options[2], s)
            self.assertEqual(result['gold'], 0)
            self.assertEqual(result['artifacts'], [sword])
            self.assertEqual(result['stress'], 0)
            self.assertEqual(result['probability'], 1)
            # With no gold and zero skills, the player always has a withdrawal option.
            s = state()
            self.assertTrue(matches(one(options[3], 'trigger'), s))
            result, = effects(options[3], s)
            self.assertFalse(result['artifacts'] or result['events'] or result['found'])
            self.assertEqual(result['stress'], 0)

    def test_stale_choices_never_charge_or_duplicate(self):
        for n, (sword, cost, _, _) in enumerate(SWORDS, 1):
            options = [v for k, _, v in self.events[f'meitou_travel.{100+n:04}'] if k == 'option']
            # Another player acquired the sword after this event opened.
            for opt in options[:3]:
                s = state(skill=30, gold=cost)
                s['found'].add(f'meitou_{sword}_found')
                self.assertFalse(matches(one(opt, 'trigger'), s))
                result, = effects(opt, s)  # Deliberately bypass the UI trigger.
                self.assertEqual(result['gold'], cost)
                self.assertFalse(result['artifacts'])
                self.assertEqual(result['stress'], 0)
                self.assertEqual(result['events'], ['meitou_travel.0999'])
            s = state(gold=cost-1)
            result, = effects(options[2], s)  # Funds disappeared after opening.
            self.assertEqual(result['gold'], cost-1)
            self.assertFalse(result['artifacts'])
            self.assertEqual(result['events'], ['meitou_travel.0999'])
            s = state()
            s['found'].add(f'meitou_{sword}_found')
            self.assertTrue(matches(one(options[4], 'trigger'), s))


if __name__ == '__main__':
    unittest.main()
