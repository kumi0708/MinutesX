# MinutesX

MinutesX は、Windows 向けのローカル議事録作成アプリです。

マイク音声と PC の再生音声を取り込み、会議の文字起こしを作成します。文字起こしは `faster-whisper` を使ってローカルで実行します。クラウドの文字起こし API は使いません。

Ollama を入れている場合は、Stop ボタンを押したあとに文字起こし内容を要約できます。

## できること

- マイク音声の録音と文字起こし
- Web 会議などの PC 音声の録音と文字起こし
- 音声ファイルの読み込みと文字起こし
- Ollama による議事録要約
- 結果を `transcripts/` に Markdown ファイルとして保存

## 必要なもの

- Windows
- Python 3.10 / 3.11 / 3.12
- [uv](https://docs.astral.sh/uv/)
- 要約を使う場合: [Ollama](https://ollama.com/)

## インストール

リポジトリを取得します。

```powershell
git clone https://github.com/kumi0708/MinutesX.git
cd MinutesX
```

依存パッケージをインストールします。

```powershell
uv sync
```

## 起動方法

次のコマンドで起動します。

```powershell
uv run minutesx
```

または、Windows で `Start-MinutesX.bat` をダブルクリックして起動できます。

初回の文字起こし時には Whisper モデルがダウンロードされることがあります。モデルが一度キャッシュされると、以後の文字起こしはローカルで実行できます。

## 基本的な使い方

1. `Mic` でマイクを選びます。
2. `PC audio` で PC 音声の入力を選びます。
3. 使わない音声は `Mute` にします。
4. `Model` で Whisper モデルを選びます。
5. `Start` を押して録音を開始します。
6. `Stop` を押すと録音を停止します。
7. Stop 後、残りの文字起こしが終わると要約が始まります。

出力ファイルは `transcripts/` に保存されます。

## 要約機能を使う場合

要約には Ollama が必要です。Ollama をインストールしたあと、使いたいモデルを取得します。

例:

```powershell
ollama pull gemma4:latest
```

MinutesX を起動し、画面上の `Ollama` 欄でモデルを選びます。

録音後に `Stop` を押すと、画面に次のような状態が表示されます。

```text
[要約待機中] 残りの文字起こしが終わったら要約します。
[要約中] 文字起こしを要約しています...
```

Ollama が起動していない場合やモデルが存在しない場合、要約は失敗します。その場合は Ollama を起動し、モデル名が正しいか確認してください。

## モデルの目安

- `base`: 軽いが精度は低め
- `small`: 日本語会議では最初に試すのにおすすめ
- `medium`: 精度は上がるが、より高い PC 性能が必要

## 注意点

- PC 音声は Windows の loopback デバイスとして表示されることがあります。
- PC 音声が見つからない場合は、Windows で音を再生した状態で `Refresh` を押してください。
- 個人設定は `minutesx-settings.json` に保存されます。
- 生成された議事録、個人設定、デバッグ音声、仮想環境は Git 管理から除外しています。

## 開発者向け

構文チェック:

```powershell
uv run python -m compileall minutesx
```
