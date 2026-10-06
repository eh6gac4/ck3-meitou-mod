# 非公開Workshop同期

- 投稿: https://steamcommunity.com/sharedfiles/filedetails/?id=3814504961
- 公開範囲: 非公開（作成者のみ）
- 現在の版: v0.10.8。入手イベントは刀ごとに0.5%、強化イベントは対象地域への到着ごとに10%。
- 同じSteamアカウントで購読済み。Steam DeckでSteamのダウンロード完了後、CK3ランチャーのプレイセットへ追加して有効化する。
- Workshopで同期するのはアップロード済みのModファイル。ローカル編集は再アップロードが必要。ランチャーの有効化状態やロード順は別途設定する。

## 更新

Steamへログインしてから `python3 scripts/workshop_private.py --upload` を実行する。
引数なしは既存投稿の読み取りのみ。公開範囲は常に非公開に固定する。
`workshop-item.json` とModの `remote_file_id` は同じ投稿IDを保持する。
Steam Workshop規約への同意が要求された場合は本人がSteam上で対応する。

LinuxのCK3付属Steam APIを利用する。発生率を変更したときはアップロード用の説明文も更新する。
