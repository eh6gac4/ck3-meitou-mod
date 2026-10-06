"""CK3 private Workshop upload using the running Linux Steam client.
Read-only by default; --upload creates/updates PRIVATE content and subscribes.
Requires the installed CK3 libsteam_api.so and an authenticated Steam client.
"""
import argparse
import ctypes as c
import json
import os
from pathlib import Path
import re
import time

APP = 1158310
ROOT = Path(__file__).resolve().parents[1]
LIB = Path.home() / '.local/share/Steam/steamapps/common/Crusader Kings III/binaries/libsteam_api.so'
TITLE = 'Meitou: Japanese Famous Swords'
U64, U32, I32, PTR, BOOL = c.c_uint64, c.c_uint32, c.c_int32, c.c_void_p, c.c_bool

class Packed(c.Structure):
    _layout_ = "ms"  # Explicit packed layout for ctypes 3.14+
    _pack_ = 4  # Steamworks Linux callback ABI
class QueryResult(Packed):
    _fields_ = [('handle', U64), ('result', I32), ('count', U32), ('total', U32), ('cached', BOOL), ('cursor', c.c_char * 256)]
class Created(Packed):
    _fields_ = [('result', I32), ('item', U64), ('legal', BOOL)]
class Submitted(Packed):
    _fields_ = [('result', I32), ('legal', BOOL), ('item', U64)]
class Subscribed(Packed):
    _fields_ = [('result', I32), ('item', U64)]
class DetailsPrefix(Packed):
    _fields_ = [('item', U64), ('result', I32), ('kind', I32), ('creator', U32), ('consumer', U32),
                ('title', c.c_char * 129), ('description', c.c_char * 8000), ('owner', U64),
                ('created', U32), ('updated', U32), ('added', U32), ('visibility', I32)]

os.environ['SteamAppId'] = str(APP)
os.environ['SteamGameId'] = str(APP)
s = c.CDLL(str(LIB))
def fn(name, result, *args):
    f = getattr(s, 'SteamAPI_' + name)
    f.restype, f.argtypes = result, list(args)
    return f

init = fn('Init', BOOL)
shutdown = fn('Shutdown', None)
pump = fn('RunCallbacks', None)
def wait(call, cls, callback, timeout=180):
    if not call:
        raise RuntimeError('Invalid Steam API call')
    failed = BOOL()
    deadline = time.monotonic() + timeout
    while not completed(utils, call, c.byref(failed)):
        if time.monotonic() >= deadline:
            raise TimeoutError('Steam call timed out; inspect existing item before retrying')
        pump()
        time.sleep(0.2)
    value = cls()
    ok = get_result(utils, call, c.byref(value), c.sizeof(value), callback, c.byref(failed))
    if not ok or failed.value:
        raise RuntimeError(f'Steam callback {callback} retrieval failed (size={c.sizeof(value)})')
    if value.result != 1:
        raise RuntimeError(f'Steam callback {callback} returned EResult={value.result}')
    return value

def query(handle):
    try:
        result = wait(send(ugc, handle), QueryResult, 3401)
        items = []
        for i in range(result.count):
            buffer = c.create_string_buffer(32768)
            assert get_details(ugc, handle, i, buffer)
            d = DetailsPrefix.from_buffer(buffer)
            assert d.result == 1 and d.consumer == APP
            items.append(dict(id=d.item, title=d.title.decode(), visibility=d.visibility, owner=d.owner))
        return items, result.total
    finally:
        release(ugc, handle)

def inspect(item):
    ids = (U64 * 1)(item)
    return query(details_query(ugc, ids, 1))[0][0]

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--upload', action='store_true')
    parser.add_argument('--item', type=int)
    args = parser.parse_args()
    if not init():
        raise SystemExit('Steam initialization failed; start Steam and log in')
    try:
        ugc = fn('SteamUGC_v016', PTR)()
        utils = fn('SteamUtils_v010', PTR)()
        user = fn('SteamUser_v021', PTR)()
        assert fn('ISteamUser_BLoggedOn', BOOL, PTR)(user)
        owner = fn('ISteamUser_GetSteamID', U64, PTR)(user)
        completed = fn('ISteamUtils_IsAPICallCompleted', BOOL, PTR, U64, c.POINTER(BOOL))
        get_result = fn('ISteamUtils_GetAPICallResult', BOOL, PTR, U64, PTR, I32, I32, c.POINTER(BOOL))
        send = fn('ISteamUGC_SendQueryUGCRequest', U64, PTR, U64)
        release = fn('ISteamUGC_ReleaseQueryUGCRequest', BOOL, PTR, U64)
        get_details = fn('ISteamUGC_GetQueryUGCResult', BOOL, PTR, U64, U32, PTR)
        details_query = fn('ISteamUGC_CreateQueryUGCDetailsRequest', U64, PTR, c.POINTER(U64), U32)
        user_query = fn('ISteamUGC_CreateQueryUserUGCRequest', U64, PTR, U32, I32, I32, I32, U32, U32, U32)
        items, page = [], 1
        while True:
            part, total = query(user_query(ugc, owner & 0xffffffff, 0, 0, 0, APP, APP, page))
            items.extend(part)
            if len(items) >= total or not part:
                break
            page += 1
        print(json.dumps({'published_items': items}, ensure_ascii=False), flush=True)
        if not args.upload:
            raise SystemExit(0)
        assert (ROOT / 'assets/workshop_preview.jpg').is_file()
        assert (ROOT / 'meitou_mod/descriptor.mod').is_file()
        matches = [i for i in items if i['title'] == TITLE]
        saved = ROOT / 'workshop-item.json'
        item = args.item or (json.loads(saved.read_text())['id'] if saved.exists() else None)
        if not item and matches:
            assert len(matches) == 1, 'Multiple matching items; specify --item'
            item = matches[0]['id']
        if item:
            existing = inspect(item)
            assert existing['owner'] == owner
            assert existing['title'] in (TITLE, ''), 'Saved item has an unexpected title'
        else:
            created = wait(fn('ISteamUGC_CreateItem', U64, PTR, U32, I32)(ugc, APP, 0), Created, 3403)
            item = created.item
            (ROOT / 'workshop-item.json').write_text(json.dumps({'id': item, 'visibility': 'private'}, indent=2) + '\n')
            print(json.dumps({'created_item': item, 'legal_agreement_required': created.legal}), flush=True)
        descriptor = ROOT / 'meitou_mod/descriptor.mod'
        text = descriptor.read_text()
        if re.search(r'^remote_file_id=', text, re.M):
            text = re.sub(r'^remote_file_id=.*$', f'remote_file_id="{item}"', text, flags=re.M)
        else:
            text = text.rstrip() + f'\nremote_file_id="{item}"\n'
        descriptor.write_text(text)
        version = re.search(r'^version="([^"]+)"', text, re.M).group(1)
        update = fn('ISteamUGC_StartItemUpdate', U64, PTR, U32, U64)(ugc, APP, item)
        assert update != 0xffffffffffffffff
        assert fn('ISteamUGC_SetItemVisibility', BOOL, PTR, U64, I32)(ugc, update, 2)
        description = ('Private personal build for desktop / Steam Deck synchronization.\n'
                       'Eight Japanese famous swords, travel acquisition events, repeatable sword upgrades, '
                       'and original icons for Ookanehira, Juzumaru and Onimaru. Japanese and English.\n'
                       f'Current build: v{version}. Travel event chances are currently set to 100% for testing; '
                       'other eligibility and cooldown conditions still apply. Uses All Under Heaven assets.')
        for method, value in [('SetItemTitle', TITLE), ('SetItemDescription', description),
                              ('SetItemContent', str(ROOT / 'meitou_mod')),
                              ('SetItemPreview', str(ROOT / 'assets/workshop_preview.jpg'))]:
            assert fn('ISteamUGC_' + method, BOOL, PTR, U64, c.c_char_p)(ugc, update, value.encode()), method
        print('Submitting PRIVATE Workshop item ' + str(item), flush=True)
        submitted = wait(fn('ISteamUGC_SubmitItemUpdate', U64, PTR, U64, c.c_char_p)(ugc, update, f'Private Steam Deck sync build v{version}'.encode()), Submitted, 3404)
        verified = inspect(item)
        assert verified['visibility'] == 2 and verified['owner'] == owner
        subscribed = wait(fn('ISteamUGC_SubscribeItem', U64, PTR, U64)(ugc, item), Subscribed, 1313)
        print(json.dumps({'verified': verified, 'subscribed': subscribed.item,
                          'legal_agreement_required': submitted.legal,
                          'url': f'https://steamcommunity.com/sharedfiles/filedetails/?id={item}'}, ensure_ascii=False), flush=True)
    finally:
        shutdown()
