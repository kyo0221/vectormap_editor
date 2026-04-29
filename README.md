# ベクターマップエディタ (OSM XML形式)

計画書に基づいた軽量なベクターマップエディタです。

## 実装機能

- `sample_image/lane.png` を背景画像として読み込み
- キャンバスのズーム・パン (pyqtgraph)
- ポイント作成
- ラインストリング作成
- エリア作成
- Lanelet作成 (既存ラインIDから参照)
- Lanelet接続作成
- hoverによるLineString ID / Lanelet IDの表示
- pixel座標からlocal meter座標への変換
- `.osm`拡張子のOSM XML形式で保存・読み込み

## インストール

### 必要環境

- Python 3.10 以上
- pip

### セットアップ

```bash
cd /path/to/vectormap_editor
python3 -m pip install -e .
```

## エディタの起動

```bash
python3 -m vector_map_editor.main
```

または、コンソールコマンドで:

```bash
vector-map-editor
```

## 使い方ガイド

### メイン画面レイアウト

```
┌─────────────────────────────────────────────────────────┐
│ メニューバー (ファイル、ツール)                              │
├─────────┬──────────────────────────────┬────────────────┤
│ ツール   │                              │ マップ概要      │
│ パネル   │    キャンバス (地図編集)      │ パネル         │
│         │                              │ - ポイント数    │
│         │                              │ - ライン数      │
│         │                              │ - レーン数      │
│         │                              │ - 接続数        │
├─────────┴──────────────────────────────┴────────────────┤
│ ステータスバー (現在のモード、メッセージ)                    │
└─────────────────────────────────────────────────────────┘
```

### ツールモード

#### 1. 選択モード (キーボード: V)

- **左クリック**: 近くの要素を選択
- 選択した要素を削除: **Delete キー**
- **用途**: マップ要素の確認

#### 2. ポイントモード (キーボード: P)

- **左クリック**: クリック位置に新しいポイントを追加
- ポイントには自動的に一意なIDが割り当てられます
- **戻す**: **Ctrl+Z** で直前に追加したポイントを取り消します

#### 3. ラインストリング / エリアモード (キーボード: L)

- 左パネルの **Class** で `Type` と `Subtype` を選択
- `Type=LineString`: `solid`, `dashed`, `road_border`, `stop_line` を選択可能
- `Type=Area`: `crosswalk` を選択可能
- **左クリック**: 図形に点を追加
- **右クリック** または **Enter**: 図形を確定
- **Esc**: ラインの作成をキャンセル (追加済みの点は削除されます)
- **最小要件**: 有効なLineString/Areaには2点以上必要

### Assistタブ

`Assist` タブで **Enable** をONにすると、LineString作成時のクリックが白pixel追跡モードになります。

- 1点目: 始点を選択します。クリック位置の近傍にある白pixelへ吸着します。
- 2点目以降: 直前の点からクリックした終点まで、2値化画像上で接続された白pixelをA*探索で辿り、3m間隔の経由点として追加します。
- 白pixelが近くにない場合、または始点と終点が白pixelで接続されていない場合は、点を追加せずエラーを表示します。

白pixel判定はgray値が40より大きいpixelを対象にします。クリック位置の30pixel以内にある白pixelへ吸着します。

**Resample LineString** は、入力したLineString IDの点列を3m間隔に再配置します。Resample後も **Ctrl+Z** で取り消せます。

### 座標系

キャンバス上のクリック位置は背景画像のpixel座標として取得され、内部データと保存ファイルではlocal meter座標として管理されます。local座標の原点は画像原点です。

変換には、提供されたECEF→pixel変換式の線形部分を逆変換したものを使用します。

### Laneletを作成する

Laneletは既存のLineString IDを参照して作成します。`Subtype` は `road`、`Turn` は `unknown`, `straight`, `left`, `right`, `merge`, `branch`, `u_turn` から選択できます。

**手順:**

1. まず3つのラインストリングを作成:
   - 左側の境界線
   - 右側の境界線
   - 中心線

2. ラインIDをメモします (ステータスバーに表示)

3. 左パネルの **レーン** セクションに移動

4. 3つのラインIDを入力:
   - 左側のラインID
   - 右側のラインID
   - 中心線ID

5. **Create Lanelet** ボタンをクリック

### Lanelet接続を作成する

接続はLanelet同士の繋がり方を定義します。分岐路は、1つのfrom Laneletから複数のto Laneletへの接続としてOSM XMLに出力されます。

**手順:**

1. 少なくとも2つのレーンを作成

2. 左パネルの **接続** セクションに移動

3. 以下を入力:
   - **開始レーンID**: スタートのレーン
   - **終了レーンID**: ゴールのレーン
   - **種類**: 接続の種類 (straight=直進、left=左折、right=右折、merge=合流、branch=分岐、u_turn=Uターン)

4. **接続を作成** ボタンをクリック

### 背景画像を使う

起動時に `sample_image/lane.png` が自動で読み込まれます。画像パネルの **Load lane.png** で再読み込みできます。

**透明度スライダー** を調整して背景とマップの両方を表示できます。

**キャンバス操作:**
- **マウスホイール**: ズームイン・アウト
- **中央クリック + ドラッグ**: キャンバスを移動
- **右クリック + ドラッグ**: 別の移動方法

### キーボードショートカット

| キー | 操作 |
|-----|--------|
| **V** | 選択モード |
| **P** | ポイントモード |
| **L** | ラインストリングモード |
| **Enter** | 作成中の図形を確定 (ラインモード) |
| **Esc** | 作成中の図形をキャンセル (ラインモード) |
| **Delete** | 選択要素を削除 |
| **Ctrl+S** | マップをOSM XMLで保存 |
| **Ctrl+O** | OSM/XMLマップを開く |
| **Ctrl+Z** | 直前の作成操作を戻す |
| **Ctrl+Y** | やり直す (将来の機能) |

### ファイルメニュー

- **新規**: 空のマップを作成
- **Open OSM/XML**: 前に保存したベクターマップを読み込み
- **Save OSM**: 現在のマップを`.osm`ファイルに保存
- **終了**: アプリケーションを閉じる

### 編集メニュー

- **Undo**: 直前に作成したPoint、作図中のPoint、LineString、Area、Lanelet、Connectionを取り消します

## OSM XML ファイル形式

マップは`.osm`拡張子のXMLファイルとして保存されます。`location` と `one_way` は出力しません。

### 構造例

```xml
<?xml version="1.0" encoding="utf-8"?>
<osm version="0.6" generator="vector_map_editor" map_id="course_001" map_version="0.1.0" frame_id="map">
  <node id="1" visible="true" version="1" x="0.0" y="0.0" z="0.0" />
  <node id="2" visible="true" version="1" x="5.0" y="0.0" z="0.0" />
  <way id="101" visible="true" version="1">
    <nd ref="1" />
    <nd ref="2" />
    <tag k="type" v="LineString" />
    <tag k="subtype" v="solid" />
  </way>
  <relation id="301" visible="true" version="1">
    <member type="way" ref="101" role="left" />
    <member type="way" ref="102" role="right" />
    <tag k="subtype" v="road" />
    <tag k="type" v="lanelet" />
    <tag k="turn_direction" v="left" />
  </relation>
</osm>
```

### 列挙値

**LineString subtype**: solid=実線、dashed=破線、road_border=道路境界、stop_line=停止線

**Lanelet subtype**: road=道路

**Area subtype**: crosswalk=横断歩道

**connection_type (接続種類)**: unknown=不明、straight=直進、left=左折、right=右折、merge=合流、branch=分岐、u_turn=Uターン

## 操作例

### シンプルなコース地図を作成する

1. **背景画像を読み込む**
   - 起動時に `sample_image/lane.png` が自動で読み込まれます
   - 透明度を調整して詳細を確認

2. **左側の境界線を作成**
   - Classで `Type=LineString`, `Subtype=solid` などを選択
   - **L** キーを押す
   - 左側の端に沿って点をクリック
   - **Enter** を押して確定
   - ラインID (例: 101) をメモ

3. **右側の境界線を作成**
   - **L** キーを再度押す
   - 右側の端に沿って点をクリック
   - **Enter** を押して確定
   - ラインID (例: 102) をメモ

4. **中心線を作成**
   - **L** キーを押す
   - 中央のパスに沿って点をクリック
   - **Enter** を押して確定
   - ラインID (例: 201) をメモ

5. **Laneletを作成**
   - 左パネルの「Lanelet」セクションに移動
   - 入力: 左=101、右=102、中心=201
   - 交差点では `Turn=left` などを選択
   - **Create Lanelet** をクリック
   - Lanelet ID: 301

6. **地図を保存**
   - **Ctrl+S** を押す
   - 保存場所とファイル名を選択
   - `.osm`として保存

7. **保存した地図を読み込む**
   - **Ctrl+O** を押す
   - `.osm`ファイルを選択
   - 全要素を含んだ地図が読み込まれる

## トラブルシューティング

### 「ラインは最低2ポイント必要です」というエラー
ラインを確定する前に最低2点をクリックしてください。少なくとも2回クリックしてから Enter を押してください。

### 「レーンラインIDは整数である必要があります」というエラー
数値のIDのみを入力してください。ステータスバーでライン作成後のIDを確認してください。

### 「レーンの境界が無効です」というエラー
参照しているラインIDのいくつかが存在していません。IDを再確認し、全てのラインが先に作成されていることを確認してください。

### 背景画像が表示されない
`sample_image/lane.png` が存在し、読めることを確認してください。

## テスト実行

OSM XML保存・読み込みテストを実行:

```bash
python3 -m pytest tests/test_xml_io.py -v
```
