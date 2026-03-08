import pyxel
import math
import random
import json
import os
import sys
import base64
import threading
import queue

# ── Thrustmaster T-300 RS / 汎用ジョイスティック対応 ──
# pygameのjoystick APIを使用。インストール: pip install pygame
try:
    import pygame as _pg
    _pg.init()
    _pg.joystick.init()
    _JOY = _pg.joystick.Joystick(0) if _pg.joystick.get_count() > 0 else None
    if _JOY:
        _JOY.init()
        print(f"[Joystick] {_JOY.get_name()} ({_JOY.get_numaxes()} axes, {_JOY.get_numbuttons()} buttons)")
    _HAS_JOY = _JOY is not None
except Exception as _joy_err:
    _HAS_JOY = False
    _JOY     = None

def _joy_axis(idx, deadzone=0.04):
    """軸の値を取得。デッドゾーン処理済み (-1.0〜1.0)。"""
    if not _HAS_JOY: return 0.0
    try:
        _pg.event.pump()   # イベントキューを更新
        v = _JOY.get_axis(idx)
        return v if abs(v) > deadzone else 0.0
    except Exception: return 0.0

def _joy_btn(idx):
    """ボタンの押下状態を取得。"""
    if not _HAS_JOY: return False
    try:
        _pg.event.pump()
        return bool(_JOY.get_button(idx))
    except Exception: return False

def _joy_hat(hat_idx=0):
    """十字キー(Hat)の状態を取得。(x, y) タプル。x: -1=左/+1=右, y: -1=下/+1=上"""
    if not _HAS_JOY: return (0, 0)
    try:
        _pg.event.pump()
        return _JOY.get_hat(hat_idx)
    except Exception: return (0, 0)

# T-300 RS ボタン番号マッピング（PC接続モード）
# Btn 4  = 左パドル  → シフトダウン
# Btn 5  = 右パドル  → シフトアップ
# Btn 7  = R2ボタン  → ニトロ（ブースト）
# Btn 9  = OPTIONSボタン → ESC（ポーズ）
# Hat 0  = 十字キー  → WASD相当（メニュー操作）

# ──────────────────────────────────────────────────────────────────────────────
# Supabase Realtime Broadcast を使ったP2P中継クライアント
#
# 【セットアップ手順】
# 1. https://supabase.com で無料アカウント作成（クレカ不要）
# 2. 新規プロジェクト作成 → Settings > API で以下2つをコピー
#      SUPABASE_URL  = "https://xxxx.supabase.co"
#      SUPABASE_ANON_KEY = "eyJ..."
# 3. 下の2変数を書き換えるだけで動作（サーバー不要・常時起動・無料）
#
# 【Renderとの違い】
#   旧: Render中継サーバー → 15分スリープ→コールドスタートラグ、帯域制限
#   新: Supabase Realtime  → 常時起動、直接broadcast、ラグ30-80ms
# ──────────────────────────────────────────────────────────────────────────────
SUPABASE_URL      = "https://mreguvyqoehrnpdcebix.supabase.co"   # ← 自分のURLに変更
SUPABASE_ANON_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Im1yZWd1dnlxb2Vocm5wZGNlYml4Iiwicm9sZSI6ImFub24iLCJpYXQiOjE3NzI4Njk4MzUsImV4cCI6MjA4ODQ0NTgzNX0.PiEvIFxYNySItxRd2hVlGyVoXpyMo6mgfJORyYUjK-0"                 # ← 自分のキーに変更

try:
    import websockets as _ws
    import asyncio as _asyncio
    _HAS_WS = True
except ImportError:
    _HAS_WS = False

import time as _time

class OnlineClient:
    """
    Supabase Realtime Broadcast を使ったオンラインクライアント。
    設計原則: ws.recv() を呼ぶのは _loop() だけ（同時recv競合を防ぐ）
    - phx_joinのackは asyncio.Event で _loop() → _handshake_done に通知
    - broadcastメッセージは recv_q (dict) に積む
    - 送信は send_q (JSON文字列) 経由で _loop() が行う
    """
    _WS_TEMPLATE = "{base}/realtime/v1/websocket?apikey={key}&vsn=1.0.0"

    def __init__(self, url, room_id, player_id):
        self.room_id   = room_id
        self.player_id = player_id
        self.send_q    = queue.Queue(maxsize=8)
        self.recv_q    = queue.Queue()
        self.connected = False
        self.error     = ""
        self._last_send_t  = 0.0
        self.SEND_INTERVAL = 1.0 / 20   # 20Hz

        base = SUPABASE_URL.replace("https://", "wss://").replace("http://", "ws://")
        self._ws_url  = self._WS_TEMPLATE.format(base=base, key=SUPABASE_ANON_KEY)
        self._channel = f"realtime:highway_racer:{room_id}"

        threading.Thread(target=self._run, daemon=True).start()

    def _run(self):
        _asyncio.run(self._main())

    async def _main(self):
        backoff = 1.0
        while True:
            try:
                async with _ws.connect(
                    self._ws_url,
                    open_timeout=15,
                    ping_interval=25,
                    ping_timeout=10,
                    extra_headers={"apikey": SUPABASE_ANON_KEY},
                ) as ws:
                    self.error = ""
                    backoff    = 1.0
                    await self._loop(ws)
            except Exception as e:
                self.connected = False
                self.error = str(e)
                print(f"[OnlineClient] 切断/エラー: {e}")
                await _asyncio.sleep(min(backoff, 10.0))
                backoff *= 1.5

    async def _loop(self, ws):
        """
        受信・送信・heartbeatを1つのコルーチンで管理。
        ws.recv() を呼ぶのはここだけ → concurrent recv エラーを完全回避。
        """
        # 1. phx_join 送信
        await ws.send(json.dumps({
            "topic":   self._channel,
            "event":   "phx_join",
            "payload": {
                "config": {
                    "broadcast": {"self": False, "ack": False},
                    "presence":  {"key": ""},
                }
            },
            "ref": "1"
        }))
        print(f"[OnlineClient] phx_join 送信: {self._channel}")

        join_ok      = False
        heartbeat_t  = _asyncio.get_running_loop().time()
        hb_ref       = 1

        while True:
            # ── 送信キューを全部捌く（ノンブロッキング）──
            while not self.send_q.empty():
                try:
                    payload_str = self.send_q.get_nowait()
                    inner = json.loads(payload_str)
                    msg = {
                        "topic":   self._channel,
                        "event":   "broadcast",
                        "payload": {"event": "game", "payload": inner},
                        "ref":     None,
                    }
                    await ws.send(json.dumps(msg))
                except queue.Empty:
                    break
                except Exception as e:
                    print(f"[OnlineClient] 送信エラー: {e}")
                    return

            # ── heartbeat (20秒ごと) ──
            now = _asyncio.get_running_loop().time()
            if now - heartbeat_t >= 20.0:
                hb_ref += 1
                heartbeat_t = now
                try:
                    await ws.send(json.dumps({
                        "topic": "phoenix", "event": "heartbeat",
                        "payload": {}, "ref": str(hb_ref)
                    }))
                except Exception as e:
                    print(f"[OnlineClient] heartbeatエラー: {e}")
                    return

            # ── 受信（タイムアウト付き: 送信・heartbeatを止めないため短く）──
            try:
                raw = await _asyncio.wait_for(ws.recv(), timeout=0.05)
            except _asyncio.TimeoutError:
                continue
            except Exception as e:
                print(f"[OnlineClient] 受信エラー: {e}")
                return

            try:
                msg = json.loads(raw)
            except Exception:
                continue

            ev = msg.get("event", "")

            # phx_join の ack → connected=True にする
            if ev == "phx_reply" and not join_ok:
                status = msg.get("payload", {}).get("status", "")
                if status == "ok":
                    join_ok = True
                    self.connected = True
                    print(f"[OnlineClient] チャンネル参加成功: {self._channel}")
                else:
                    print(f"[OnlineClient] phx_join 失敗: {msg}")
                    return
                continue

            # broadcast メッセージをゲームループへ渡す
            if ev == "broadcast":
                inner = msg.get("payload", {}).get("payload")
                if isinstance(inner, dict):
                    if self.recv_q.qsize() > 20:
                        try: self.recv_q.get_nowait()
                        except: pass
                    self.recv_q.put(inner)

    # ── ゲームループから呼ぶ公開メソッド ──────────────────────────────────

    def send(self, data: dict):
        """スロットリング付き送信（20Hz上限）。位置データ等に使用。"""
        now = _time.monotonic()
        if now - self._last_send_t < self.SEND_INTERVAL:
            return
        self._last_send_t = now
        self._enqueue(data, now)

    def send_priority(self, data: dict):
        """スロットリングなし送信。start/join/settings等の制御メッセージに使用。"""
        now = _time.monotonic()
        self._last_send_t = now
        self._enqueue(data, now)

    def _enqueue(self, data: dict, now: float):
        data["t"] = now
        payload = json.dumps(data)
        if self.send_q.full():
            try: self.send_q.get_nowait()
            except: pass
        try: self.send_q.put_nowait(payload)
        except: pass

    def recv_all(self) -> list:
        """受信キューを全て取り出して返す（要素はdict）。"""
        out = []
        while not self.recv_q.empty():
            try:
                item = self.recv_q.get_nowait()
                if isinstance(item, dict):
                    out.append(item)
            except: pass
        return out


# ── ピア補間エンジン ──────────────────────────────────────────────────────────
class PeerInterpolator:
    """
    受信パケット間を滑らかに補間して相手の位置ガタつきを除去する。

    アルゴリズム:
      - 受信パケットをスナップショットバッファ(最大8件)に蓄積
      - 描画時は「現在時刻 - INTERP_DELAY だけ前」のスナップショットを
        前後2点の線形補間で求める（バッファリング補間）
      - バッファが空・遅延オーバー時はデッドレコニングにフォールバック

    これにより:
      - 受信間隔のバラつき(ジッター)を吸収
      - 急なジャンプを消す
      - ラグは INTERP_DELAY(100ms)増えるが滑らかになる
    """
    INTERP_DELAY = 0.10   # バッファリング遅延(秒)。小さいほどリアルタイム/ガタつく
    MAX_SNAPS    = 8      # スナップショットバッファサイズ

    def __init__(self):
        self.snaps  = []   # [(recv_time, {x,y,angle,vx,vy,vel,...}), ...]
        self.render = {}   # 補間済みの描画用状態

    def push(self, snap: dict, recv_time: float):
        """新しいスナップショットを追加"""
        # タイムスタンプが古いパケットは無視
        if self.snaps and snap.get("t", 0) <= self.snaps[-1][1].get("t", 0):
            return
        self.snaps.append((recv_time, snap))
        if len(self.snaps) > self.MAX_SNAPS:
            self.snaps.pop(0)

    def update(self, now: float) -> dict:
        """
        now時刻でのレンダリング用状態を計算して返す。
        バッファリング補間 → デッドレコニングの順でフォールバック。
        """
        target_t = now - self.INTERP_DELAY

        # ── ① バッファリング補間 ──
        if len(self.snaps) >= 2:
            # target_t を挟む2スナップショットを探す
            for i in range(len(self.snaps) - 1):
                t0, s0 = self.snaps[i]
                t1, s1 = self.snaps[i + 1]
                if t0 <= target_t <= t1:
                    alpha = (target_t - t0) / max(t1 - t0, 1e-6)
                    alpha = max(0.0, min(1.0, alpha))
                    self.render = self._lerp(s0, s1, alpha)
                    return self.render

        # ── ② デッドレコニング（最新スナップから外挿）──
        if self.snaps:
            _, s = self.snaps[-1]
            dt = min(now - self.snaps[-1][0], 0.25)
            vx = s.get("vx", math.cos(s.get("angle", 0)) * s.get("vel", 0))
            vy = s.get("vy", math.sin(s.get("angle", 0)) * s.get("vel", 0))
            pred = dict(s)
            pred["x"] = s.get("x", 0) + vx * dt * 30
            pred["y"] = s.get("y", 0) + vy * dt * 30
            # render との差が大きすぎる場合は急に補正せず lerp で寄せる
            if self.render:
                err = math.hypot(pred["x"] - self.render.get("x", pred["x"]),
                                 pred["y"] - self.render.get("y", pred["y"]))
                a = min(0.15, err * 0.03) if err < 5.0 else 0.4
                self.render["x"]     = self.render.get("x", pred["x"])     + (pred["x"]     - self.render.get("x",     pred["x"]))     * a
                self.render["y"]     = self.render.get("y", pred["y"])     + (pred["y"]     - self.render.get("y",     pred["y"]))     * a
                self.render["angle"] = self.render.get("angle", pred["angle"]) + (pred["angle"] - self.render.get("angle", pred["angle"])) * 0.2
                self.render["vel"]   = pred.get("vel", 0)
                self.render["vx"]    = vx
                self.render["vy"]    = vy
            else:
                self.render = pred
            return self.render

        return self.render  # スナップなし → 前回値をそのまま返す

    @staticmethod
    def _lerp(a: dict, b: dict, t: float) -> dict:
        """2スナップショット間を線形補間"""
        out = dict(b)
        for k in ("x", "y", "vel", "vx", "vy"):
            va = a.get(k, 0.0)
            vb = b.get(k, 0.0)
            out[k] = va + (vb - va) * t
        # 角度は最短経路で補間（±π折り返し対応）
        aa = a.get("angle", 0.0)
        ab = b.get("angle", 0.0)
        diff = (ab - aa + math.pi) % (2 * math.pi) - math.pi
        out["angle"] = aa + diff * t
        return out

try:
    import js # type: ignore
    IS_WEB = True
except ImportError:
    IS_WEB = False

# ファイルダイアログ (tkinter) - なくてもゲームは動く
try:
    import tkinter as _tk
    from tkinter import filedialog as _fd
    _HAS_TK = True
except Exception:
    _HAS_TK = False

def _ask_open(title, ftypes):
    if not _HAS_TK: return None
    try:
        r = _tk.Tk(); r.withdraw(); r.attributes("-topmost", True)
        p = _fd.askopenfilename(title=title, filetypes=ftypes)
        r.destroy(); return p or None
    except Exception: return None

def _ask_save(title, default, ftypes):
    if not _HAS_TK: return None
    try:
        r = _tk.Tk(); r.withdraw(); r.attributes("-topmost", True)
        p = _fd.asksaveasfilename(title=title, initialfile=default,
                                  defaultextension=".json", filetypes=ftypes)
        r.destroy(); return p or None
    except Exception: return None

class RivalCar:
    def __init__(self, color, start_pos, start_angle):
        self.x = start_pos[0]
        self.y = start_pos[1]
        self.angle = start_angle
        self.velocity = 0.0
        self.vx = 0.0               # 慣性速度ベクトルX
        self.vy = 0.0               # 慣性速度ベクトルY
        self.slip_angle = 0.0       # スリップ角
        self.gear = 0
        self.rpm = 0
        self.color = color
        self.u = 49
        self.w = 0
        self.boost_timer = 0
        self.lap = 0
        self.prev_idx = 0
        self.progress = 0
        self.is_stopping = False
        self.rubber_speed    = 1.0
        self.rubber_handling = 1.0
        self.perf_scale      = 1.0    # 個別性能スケール（0.7〜1.0）
        self.rocket_timer    = 0      # ロケットスタート残フレーム
        self.is_rocket_start = False  # ロケットスタート中フラグ
        self.prev_can_move   = False  # 前フレームのcan_move（スタート瞬間検出用）
        self.smoke_particles = []     # ロケットスタート煙パーティクル

    def update(self, course_points, gear_settings, is_offroad, can_move, player_progress=0,
               racing_line=None, player_speed_scale=1.0,
               map_image=None, ground_col=11, other_rivals=None):
        # カウントダウン中
        if not can_move:
            self.u, self.w = 49, 0
            self.prev_can_move = False
            return

        # スタート瞬間：80%の確率でロケットスタート
        if not self.prev_can_move and can_move:
            if random.random() < 0.80:
                self.is_rocket_start = True
                self.rocket_timer = 80
                # 初速を付与
                self.vx = math.cos(self.angle) * 0.30
                self.vy = math.sin(self.angle) * 0.30
        self.prev_can_move = True

        # ロケットスタートタイマー管理（60km/h≈0.15で終了）
        if self.rocket_timer > 0:
            self.rocket_timer -= 1
            spd_now = (self.vx**2 + self.vy**2) ** 0.5
            if spd_now > 0.15 or self.rocket_timer == 0:
                self.rocket_timer = 0
                self.is_rocket_start = False

        # ゴール後はゆっくり減速
        if self.is_stopping:
            self.vx *= 0.982
            self.vy *= 0.982
            self.velocity = (self.vx**2 + self.vy**2) ** 0.5
            self.x += self.vx
            self.y += self.vy
            self.u, self.w = 49, 0
            return

        n = len(course_points)

        # ── 最近傍インデックス探索（局所サーチでO(n)→O(k)に高速化）──
        # 前回インデックスの前後 SEARCH_RADIUS 点だけ調べる
        SEARCH_RADIUS = 20
        best_dist = float('inf')
        closest_idx = self.prev_idx
        for offset in range(-SEARCH_RADIUS, SEARCH_RADIUS + 1):
            i = (self.prev_idx + offset) % n
            px, py = course_points[i]
            d = (px - self.x) ** 2 + (py - self.y) ** 2
            if d < best_dist:
                best_dist = d
                closest_idx = i

        if self.prev_idx > n * 0.8 and closest_idx < n * 0.2:
            self.lap += 1
        elif self.prev_idx < n * 0.2 and closest_idx > n * 0.8:
            self.lap -= 1
        self.prev_idx = closest_idx
        self.progress = self.lap * n + closest_idx

        # ── ラバーバンドAI ──
        raw_diff = self.progress - player_progress
        if raw_diff >  n * 0.5: raw_diff -= n
        elif raw_diff < -n * 0.5: raw_diff += n
        progress_diff = raw_diff
        threshold = n * 0.03

        if progress_diff > threshold:
            excess = min((progress_diff - threshold) / (n * 0.25), 1.0)
            target_speed    = 1.0 - excess * 0.15
            target_handling = 1.0 - excess * 0.10
        elif progress_diff < -threshold:
            shortage = min((-progress_diff - threshold) / (n * 0.20), 1.0)
            target_speed    = 1.0 + shortage * 0.65
            target_handling = 1.0 + shortage * 0.40
        else:
            target_speed    = 1.0
            target_handling = 1.0

        lerp_rate = 0.06 if progress_diff < -threshold else 0.03
        self.rubber_speed    += (target_speed    - self.rubber_speed)    * lerp_rate
        self.rubber_handling += (target_handling - self.rubber_handling) * lerp_rate
        if abs(progress_diff) < threshold * 0.5:
            self.rubber_speed    += (1.0 - self.rubber_speed)    * 0.08
            self.rubber_handling += (1.0 - self.rubber_handling) * 0.08

        # ── ダート（コース外）判定 ──
        cx_i = int(self.x)
        cy_i = int(self.y)
        on_dirt = False
        if map_image is not None and 0 <= cx_i < 256 and 0 <= cy_i < 256:
            pix = map_image.pget(cx_i, cy_i)
            on_dirt = (pix == ground_col)

        # ダート走行時の速度ペナルティ（プレイヤーと同等の減速）
        dirt_speed_mult = 1.0
        if on_dirt:
            dirt_speed_mult = 0.72  # コース外では大きく減速

        # ── コース逸脱防止：前方ピクセルチェック & 境界修正 ──
        # コースライン上の最近傍点をターゲットとして「強制帰還」方向を計算する
        boundary_steer_bias = 0.0   # 正=右旋回追加, 負=左旋回追加
        if map_image is not None:
            # 現在地から前方 PROBE_DIST 分を複数点サンプリングして境界を予測
            PROBE_DIST = max(3.0, (self.vx**2 + self.vy**2)**0.5 * 20)
            fwd_x_probe = math.cos(self.angle)
            fwd_y_probe = math.sin(self.angle)
            side_x_probe = -math.sin(self.angle)
            side_y_probe =  math.cos(self.angle)

            # 前方3点 × 左右3本のレーンをサンプリング
            probe_hits_left  = 0
            probe_hits_right = 0
            for dist_frac in (0.4, 0.7, 1.0):
                dist = PROBE_DIST * dist_frac
                for lane_off, is_left_probe in ((-2.5, True), (0.0, False), (2.5, False)):
                    px_p = self.x + fwd_x_probe * dist + side_x_probe * lane_off
                    py_p = self.y + fwd_y_probe * dist + side_y_probe * lane_off
                    pi_p, pj_p = int(px_p), int(py_p)
                    if 0 <= pi_p < 256 and 0 <= pj_p < 256:
                        if map_image.pget(pi_p, pj_p) == ground_col:
                            if lane_off < 0:
                                probe_hits_left += 1
                            else:
                                probe_hits_right += 1

            # ヒット数に応じてステアリングバイアスを加算（反対側に曲げる）
            # 左側がダート → 右に曲げる（正バイアス）
            # 右側がダート → 左に曲げる（負バイアス）
            if probe_hits_left > 0 or probe_hits_right > 0:
                total_hits = probe_hits_left + probe_hits_right
                # 左側のヒット割合が高いほど右へ補正
                bias_strength = min(total_hits / 6.0, 1.0) * 0.08
                boundary_steer_bias = (probe_hits_left - probe_hits_right) / max(total_hits, 1) * bias_strength
            
            # 既にダートに入っていれば強制的にコース中心へ向かわせる
            if on_dirt:
                cp_x, cp_y = course_points[closest_idx]
                center_angle = math.atan2(cp_y - self.y, cp_x - self.x)
                center_diff  = (center_angle - self.angle + math.pi) % (2 * math.pi) - math.pi
                boundary_steer_bias += center_diff * 0.25

        # ── 追い越し：前方ライバルを検知してラインをずらす ──
        overtake_offset = 0.0   # 横オフセット（正=右, 負=左）
        if other_rivals is not None:
            for other in other_rivals:
                if other is self:
                    continue
                dx_ov = other.x - self.x
                dy_ov = other.y - self.y
                dist_ov = math.hypot(dx_ov, dy_ov)
                if dist_ov < 6.0:
                    # 自分の前方にいる相手のみ対象
                    fwd_x_ov = math.cos(self.angle)
                    fwd_y_ov = math.sin(self.angle)
                    fwd_dot = dx_ov * fwd_x_ov + dy_ov * fwd_y_ov
                    if fwd_dot > 0.5:  # 前方にいる
                        # 相手が自分の左右どちらにいるか
                        side_x_ov = -math.sin(self.angle)
                        side_y_ov =  math.cos(self.angle)
                        lateral_pos = dx_ov * side_x_ov + dy_ov * side_y_ov
                        # 相手が右にいれば左へ、左にいれば右へ回避
                        avoid_dir = -1.0 if lateral_pos > 0 else 1.0
                        # 近いほど強く回避（最大±4.0の横オフセット）
                        strength = (1.0 - dist_ov / 6.0) * 4.0
                        overtake_offset += avoid_dir * strength

        # ── ステアリング・先読みにレーシングラインを使用 ──
        line = racing_line if racing_line is not None else course_points
        steer_look = max(6, int(8 + self.velocity * 15))

        # 追い越しオフセットをターゲット点に反映
        base_tx, base_ty = line[(closest_idx + steer_look) % n]
        if abs(overtake_offset) > 0.01:
            # ターゲット点に対して垂直方向へオフセットを加える
            next_pt = line[(closest_idx + steer_look + 4) % n]
            seg_dx  = next_pt[0] - base_tx
            seg_dy  = next_pt[1] - base_ty
            seg_len = math.hypot(seg_dx, seg_dy) or 1.0
            # 垂直方向（コース横断方向）
            perp_x = -seg_dy / seg_len
            perp_y =  seg_dx / seg_len
            # クランプ（大きすぎるオフセットはコース外に出る危険）
            ov_clamped = max(-3.5, min(overtake_offset, 3.5))
            tx = base_tx + perp_x * ov_clamped
            ty = base_ty + perp_y * ov_clamped
        else:
            tx, ty = base_tx, base_ty

        target_angle = math.atan2(ty - self.y, tx - self.x)
        angle_diff = (target_angle - self.angle + math.pi) % (2 * math.pi) - math.pi

        spd = (self.vx**2 + self.vy**2) ** 0.5
        # 先読み距離：低速でも十分な先を見る（最低30点）
        brake_look = max(30, int(spd * 120))
        future_angles = []
        # サンプリング間隔を細かくして誤検知を防ぐ
        step = max(2, brake_look // 10)
        for fi in range(4, brake_look, step):
            fax, fay = line[(closest_idx + fi) % n]
            fbx, fby = line[(closest_idx + fi + 4) % n]
            fa = math.atan2(fby - fay, fbx - fax)
            future_angles.append(fa)
        max_corner = 0.0
        for i in range(1, len(future_angles)):
            da = abs((future_angles[i] - future_angles[i-1] + math.pi) % (2*math.pi) - math.pi)
            max_corner = max(max_corner, da)

        # ── ブースト ──
        if max_corner < 0.08 and spd > 0.25 and self.boost_timer <= 0:
            if random.random() < 0.008:
                self.boost_timer = 90
        boost_mult = 1.0
        if self.boost_timer > 0:
            self.boost_timer -= 1
            boost_mult = 1.4

        # ── グリップ係数 ──
        if is_offroad:
            grip_base      = 0.60
            traction_limit = 0.50
        else:
            grip_base      = 0.80
            traction_limit = 0.78
        grip_base *= self.rubber_handling

        # ── ステアリング（車体向きを回す）──
        if spd > 0.01:
            steer_max    = 0.055 if not is_offroad else 0.042
            speed_factor = (spd / 0.7) ** 1.2
            steer_rate   = steer_max / (1.0 + speed_factor * 1.3)
            steer_rate   = max(steer_rate, 0.007) * self.rubber_handling
        else:
            steer_rate = 0.0

        # 境界修正バイアスを angle_diff に加算してからステアリング判定
        effective_angle_diff = angle_diff + boundary_steer_bias
        if effective_angle_diff < -0.08:
            self.angle -= steer_rate
            self.u, self.w = -50, 26
        elif effective_angle_diff > 0.08:
            self.angle += steer_rate
            self.u, self.w = 50, 26
        else:
            self.u, self.w = 49, 0

        # ── 速度コントロール（先読みコーナーに基づく）──
        fwd_x = math.cos(self.angle)
        fwd_y = math.sin(self.angle)
        speed_along_fwd = self.vx * fwd_x + self.vy * fwd_y

        corner_severity = min(max_corner / 0.8, 1.0)
        straight_bonus = 1.0 + (1.0 - corner_severity) * 0.20
        if is_offroad:
            target_spd = 0.55 - corner_severity * 0.18
        else:
            target_spd = 0.70 - corner_severity * 0.20
        target_spd *= self.rubber_speed * boost_mult * player_speed_scale * straight_bonus
        # ダート走行ペナルティを速度目標に適用
        target_spd *= dirt_speed_mult

        need_brake = spd > target_spd + 0.02

        if need_brake:
            brake_force = min((spd - target_spd) * 0.15, 0.012)
            if spd > 0.001:
                self.vx -= (self.vx / spd) * brake_force
                self.vy -= (self.vy / spd) * brake_force
        else:
            gear_set   = gear_settings[self.gear]
            max_vel    = gear_set["max_vel"] * boost_mult * self.rubber_speed * player_speed_scale
            accel_rate = 0.002 * gear_set["accel"] * boost_mult * self.rubber_speed * player_speed_scale * 0.9
            # ロケットスタート追加加速
            if self.rocket_timer > 0:
                accel_rate += 0.006 * (self.rocket_timer / 80.0)

            # ギアシフト
            spd_rpm = spd / max_vel if max_vel > 0 else 0
            self.rpm += (min(spd_rpm, 1.0) - self.rpm) * 0.2
            if self.rpm > 0.85 and self.gear < 4:
                self.gear += 1
            elif self.rpm < 0.4 and self.gear > 0:
                self.gear -= 1

            # エンジンブレーキ（ギア上限超え）
            raw_rpm = spd / max_vel if max_vel > 0 else 0
            if raw_rpm > 1.0:
                eb = 1.0 - 0.008 * (raw_rpm - 1.0)
                self.vx *= max(eb, 0.94)
                self.vy *= max(eb, 0.94)

            self.vx += fwd_x * accel_rate
            self.vy += fwd_y * accel_rate

        # ── グリップ補正（横速度を車体向きに引き戻す）──
        if spd > 0.001:
            vel_angle = math.atan2(self.vy, self.vx)
            self.slip_angle = (vel_angle - self.angle + math.pi) % (2 * math.pi) - math.pi
            slip_abs = abs(self.slip_angle)

            grip_peak = 0.38
            if slip_abs < grip_peak:
                grip_factor = grip_base * (slip_abs / grip_peak)
            else:
                over = min((slip_abs - grip_peak) / 0.5, 1.0)
                grip_factor = grip_base * (1.0 - over * 0.55)

            side_x = math.cos(self.angle + math.pi/2)
            side_y = math.sin(self.angle + math.pi/2)
            lateral_vel = self.vx * side_x + self.vy * side_y
            correction  = lateral_vel * grip_factor
            self.vx -= side_x * correction
            self.vy -= side_y * correction
        else:
            self.slip_angle = 0.0

        # 空気抵抗
        spd2 = (self.vx**2 + self.vy**2) ** 0.5
        drag = 1.0 - spd2 * 0.00086
        self.vx *= max(drag, 0.9986)
        self.vy *= max(drag, 0.9986)

        # 惰性減衰（アクセル放し）
        if not (abs(angle_diff) <= 0.35):
            pass  # ブレーキ処理済み
        else:
            self.vx *= 0.9992
            self.vy *= 0.9992

        self.velocity = (self.vx**2 + self.vy**2) ** 0.5
        self.x += self.vx
        self.y += self.vy

        # ロケットスタート中の煙パーティクル生成（ワールド座標）
        if self.is_rocket_start and self.rocket_timer > 0:
            burst = max(1, self.rocket_timer // 16)
            for _ in range(burst):
                # 車体後方方向に煙を出す
                back_x = self.x - math.cos(self.angle) * 0.3
                back_y = self.y - math.sin(self.angle) * 0.3
                self.smoke_particles.append({
                    "wx": back_x + random.uniform(-0.15, 0.15),
                    "wy": back_y + random.uniform(-0.15, 0.15),
                    "life": random.randint(10, 20),
                    "max_life": 20,
                    "size": random.uniform(1.5, 3.5),
                })
        # パーティクル更新（リスト内包表記でO(n)除去）
        for p in self.smoke_particles:
            p["life"] -= 1
            p["size"] += 0.2
        self.smoke_particles = [p for p in self.smoke_particles if p["life"] > 0]

    def draw_3d(self, cam_x, cam_y, cam_angle):
        # 道路描画と完全に一致する投影計算式
        horizon = 80
        cam_z = 40.0
        fov = 1.3
        scale_factor = 0.02

        dx = self.x - cam_x
        dy = self.y - cam_y

        sn = math.sin(cam_angle)
        cs = math.cos(cam_angle)

        # カメラ空間のローカル座標に変換
        local_z = dx * cs + dy * sn
        local_x = -dx * sn + dy * cs

        # ロケット煙のスクリーン投影描画
        for p in self.smoke_particles:
            pdx = p["wx"] - cam_x
            pdy = p["wy"] - cam_y
            plz =  pdx * cs + pdy * sn
            plx = -pdx * sn + pdy * cs
            if plz > 0.1:
                pdy_s = (cam_z * 100.0 * scale_factor) / plz
                psx   = pyxel.width / 2 + (plx * 100.0) / (fov * plz)
                psy   = horizon + pdy_s
                alpha = p["life"] / p["max_life"]
                col   = 7 if alpha > 0.6 else (13 if alpha > 0.3 else 5)
                r = max(1, int(p["size"] * (pdy_s / 62.0)))
                pyxel.circ(psx, psy, r, col)

        # カメラ空間のローカル座標に変換
        local_z = dx * cs + dy * sn
        local_x = -dx * sn + dy * cs

        # カメラの前方にある場合のみ描画
        if local_z > 0.1:
            # 道路式からの逆算でスクリーンY座標を計算
            dy_screen = (cam_z * 100.0 * scale_factor) / local_z
            screen_y = horizon + dy_screen
            
            # スクリーンX座標の計算
            px = (local_x * 100.0) / (fov * local_z)
            screen_x = (pyxel.width / 2) + px
            
            # 描画スケール（自車の描画位置 dy_screen=62 を基準(1.0)とする）
            # BASE = 80 / (CAR_HL*2) = 80/1.04 ≈ 76.92
            # → 衝突距離(local_z=1.04)のとき scale=1.0 = 自車と同じ大きさ
            scale = dy_screen / 76.92
            
            if 0.1 < scale < 5.0:
                # 接地感を出すための影（中心を screen_x, screen_y に配置）
                shadow_w = 40 * scale
                shadow_h = 10 * scale
                pyxel.elli(screen_x - shadow_w/2, screen_y - shadow_h/2, shadow_w, shadow_h, 0)
                
                # 車体の描画
                pyxel.pal(195, self.color)
                
                # ====================================================
                # 【ズレ修正】Pyxelのスケール仕様に合わせた正確な座標計算
                # 画像の高さ(24)の下端を、影の中心(screen_y)にピッタリ合わせる式
                base_y = screen_y - 12 - (12 * scale)
                
                # 画像の幅(self.u)の中心を、影の中心(screen_x)にピッタリ合わせる式
                base_x = screen_x - (abs(self.u) / 2)
                # ====================================================
                
                pyxel.blt(base_x, base_y, 0, 0, self.w, self.u, 24, 229, scale=scale)
                pyxel.pal()
            
class App:
    # ================================================================
    # デバッグ設定（本番時は 0 に変更）
    # ================================================================
    DEBUG_INITIAL_CREDITS = 5_000_000   # 初期クレジット上乗せ量

    GEAR_SETTINGS = [
                {"accel": 1.0,  "max_vel": 0.15},
                {"accel": 0.7,  "max_vel": 0.30},
                {"accel": 0.5,  "max_vel": 0.45},
                {"accel": 0.35, "max_vel": 0.55},
                {"accel": 0.30,  "max_vel": 0.70},
            ]

    # ===================================================================
    # コース定義リスト
    # ===================================================================
    COURSES = [
        {
            # ---- コース0: 筑波サーキット風 (オリジナル) ----
            "name": "TSUKUBA",
            "control_points": [
                (110, 220), (150, 220), (190, 215), (210, 195),
                (200, 165), (180, 155), (160, 140), (155, 115),
                (175, 100), (200, 105), (220, 85),  (210, 50),
                (185, 35),  (150, 45),  (100, 70),  (50, 95),
                (30, 130),  (30, 180),  (60, 210)
            ],
            "checkpoints": [(155, 115), (50, 95), (30, 180), (125, 213)],
            "start_pos":   (125.0, 220.0),
            "start_angle": 0.0,
            "start_line":  (125, 213, 2, 15),
            "road_outer":  6,
            "road_mid":    5,
            "road_inner":  4,
            "out_distance": 60,
            "col_outer":   8,
            "col_mid":     7,
            "col_inner":   5,
            "col_ground":  11,
            "night_remap": {11: 21, 5: 1, 7: 13, 8: 2},
        },
        {
            # ---- コース1: テクニカルサーキット ----
            "name": "TECHNICAL",
            "control_points": [
                (165, 178), (188, 172), (210, 168),
                (228, 162), (238, 150), (232, 138),
                (225, 120), (228, 95),  (225, 72),
                (215, 52),  (195, 40),  (172, 36),
                (148, 38),  (125, 40),  (105, 48),
                (88, 58),   (75, 72),   (68, 88),
                (58, 100),  (40, 105),  (28, 118),
                (30, 132),  (45, 140),  (62, 135),
                (72, 125),  (82, 140),  (90, 155),
                (100, 168), (118, 175),
                (142, 170), (155, 175),
            ],
            "checkpoints": [
                (238, 150), (172, 36), (28, 118), (45, 140), (142, 170), (165, 178)
            ],
            "start_pos":   (165.0, 178.0),
            "start_angle": 0.0,
            "start_line":  (159, 171, 2, 14),
            "road_outer":  5,
            "road_mid":    4,
            "road_inner":  3,
            "out_distance": 50,
            "col_outer":   8,
            "col_mid":     7,
            "col_inner":   5,
            "col_ground":  11,
            "night_remap": {11: 21, 5: 1, 7: 13, 8: 2},
        },
        {
            # ---- コース2: オーバルスピードウェイ ----
            "name": "SPEEDWAY",
            "control_points": [
                (128, 225), (162, 225), (196, 220), (220, 205),
                (236, 182), (236, 148), (236, 112), (220, 80),
                (196, 55),  (162, 40),  (128, 38),  (94, 40),
                (60, 55),   (36, 80),   (20, 112),  (20, 148),
                (20, 182),  (36, 205),  (60, 220),  (94, 225)
            ],
            "checkpoints": [
                (236, 148), (128, 38), (20, 148), (128, 225)
            ],
            "start_pos":   (128.0, 225.0),
            "start_angle": 0.0,
            "start_line":  (122, 218, 2, 14),
            "road_outer":  8,
            "road_mid":    7,
            "road_inner":  6,
            "out_distance": 70,
            "col_outer":   8,
            "col_mid":     7,
            "col_inner":   5,
            "col_ground":  11,
            "night_remap": {11: 21, 5: 1, 7: 13, 8: 2},
        },
        {
            # ---- コース3: オフロードダートトレイル ----
            "name": "OFFROAD",
            "control_points": [
                (120, 220), (148, 218), (172, 210), (190, 192),
                (196, 168), (188, 144), (170, 128), (156, 105),
                (162, 82),  (180, 65),  (194, 48),  (175, 30),
                (148, 26),  (120, 34),  (94, 50),   (70, 70),
                (55, 95),   (40, 122),  (36, 152),  (44, 178),
                (62, 198),  (88, 214),  (108, 220)
            ],
            "checkpoints": [
                (188, 144), (120, 34), (36, 152), (120, 220)
            ],
            "start_pos":   (120.0, 220.0),
            "start_angle": 0.0,
            "start_line":  (114, 213, 2, 14),
            "road_outer":  3,
            "road_mid":    2,
            "road_inner":  1,
            "out_distance": 40,
            "col_outer":   4,   # 暗い茶色(路肩の土)
            "col_mid":     9,   # オレンジ茶(轍の縁)
            "col_inner":   4,   # 茶色ダート路面
            "col_ground":  3,   # 暗い緑(下草・コースアウト色)
            "night_remap": {3: 1, 4: 2, 9: 4},
        },
    ]

    def __init__(self):
        # 実行ファイルの場所（ベースディレクトリ）を取得
        # Pyxelのapp2exeを使用した場合、sys.executable に exeのパス が入る
        exe_name = os.path.basename(sys.executable).lower()
        if "python" in exe_name or "pyxel" in exe_name:
            # 通常の .py スクリプトとして実行された場合
            base_dir = os.path.dirname(os.path.abspath(__file__))
        else:
            # app2exeでexe化されて実行された場合 (例: game6.exe)
            base_dir = os.path.dirname(sys.executable)

        # ベースディレクトリを元にファイルの絶対パスを作成
        self.save_file = os.path.join(base_dir, "best_times.json")
        self.custom_courses_file = os.path.join(base_dir, "custom_courses.json")
        self.credits_file  = os.path.join(base_dir, "credits.json")
        self.stats_file    = os.path.join(base_dir, "stats.json")
        self.options_file  = os.path.join(base_dir, "options.json")
        self.car_data_file = os.path.join(base_dir, "car_data.json")
        self.online_client  = None
        self.online_peers   = {}             # pid -> 補間済み描画用状態(dict)
        self._peer_interp   = {}             # pid -> PeerInterpolator インスタンス
        self.online_room_id = ""
        self.online_my_id   = ""
        self.online_status  = ""
        self.online_is_host = False        # True=ホスト, False=ゲスト
        self.online_entry_mode = 0         # 0=CREATE, 1=JOIN
        self.online_join_input = ""        # ルームID入力バッファ
        self.online_join_active = False    # True=テキスト入力モード中
        self.online_host_settings = {}     # ホストが送ってきた設定
        self.online_lobby_ready = False    # ホストがSTARTを押した
        self.STATE_TITLE         = 0
        self.STATE_MENU          = 1
        self.STATE_PLAY          = 2
        self.STATE_PAUSE         = 3
        self.STATE_CUSTOMIZE     = 4
        self.STATE_COURSE_SELECT = 5
        self.STATE_MODE_SELECT   = 6
        self.STATE_COURSE_MAKER  = 7
        self.STATE_STATUS        = 8
        self.STATE_OPTIONS       = 9
        self.STATE_TIME_SELECT   = 10
        self.STATE_RANKING       = 11
        self.STATE_ONLINE_LOBBY  = 12
        self.STATE_ONLINE_ENTRY  = 13

        # 画面遷移フェード
        self.fade_alpha  = 0     # 0=透明, 255=真っ黒
        self.fade_dir    = 0     # 1=暗転中, -1=明転中, 0=なし
        self.fade_target = None  # フェード完了後の遷移先ステート
        self.fade_speed  = 18    # フレームあたりの変化量

        self.state = self.STATE_TITLE
        self.menu_focus         = 0
        self.opt_focus          = 0
        self.pause_focus        = 0
        self.pause_quit_confirm = False
        self.cs_del_confirm     = False
        self.is_night_mode   = False
        self.is_automatic    = False
        self.goal_laps       = 3
        self.num_rivals      = 3   # ライバル台数 (1〜11)
        self.is_time_attack  = False
        self.selected_course = 0
        self.difficulty      = 2   # 0=初級(EASY), 1=中級(NORMAL), 2=上級(HARD)
        self.time_sel_focus  = 0   # 0=DAY, 1=NIGHT, 2=EASY, 3=NORMAL, 4=HARD, 5=START
        self.ghost_enabled   = True   # ゴースト表示ON/OFF
        self.ghost_data      = []     # 保存済みゴーストフレーム（再生用）
        self.ghost_frame_idx = 0      # 再生位置（実フレーム数）
        self.ghost_sample    = 1      # ゴーストのサンプリングレート
        self.ghost_record    = []     # 今走行中の録画バッファ
        self._share_msg       = ""    # エクスポート/インポート結果フィードバック
        self._share_msg_timer = 0

        pyxel.init(256, 192, title="Highway Racer", quit_key=pyxel.KEY_NONE)

        self.setup_sounds()
        self.setup_custom_palette()
        pyxel.images[0].load(0, 0, "car.png")
        pyxel.images[1].load(0, 0, "cloud.png")
        pyxel.images[2].load(0, 0, "title.png")

        # カスタムコースをファイルから読み込み COURSES に追加
        self._load_custom_courses()

        # 全コースのスムーズポイントを事前計算しておく
        self.course_data = []
        for course_def in self.COURSES:
            smooth_pts = self._calc_smooth_points(course_def["control_points"])
            racing_line = self._calc_racing_line(smooth_pts, course_def["road_outer"])
            self.course_data.append({"smooth_points": smooth_pts, "racing_line": racing_line})

        # 初期コースのマップをイメージバンク1に描画
        self._build_map(self.selected_course)

        self.car_color = 195
        self.best_times = self.load_best_times()
        # ランキングデータから best_lap_time を取得（後方互換）
        _init_ranking = self.best_times.get(f"ta_ranking_{self.COURSES[self.selected_course]['name']}", [])
        self.best_lap_time = _init_ranking[0] if _init_ranking else self.best_times.get(self._course_key(), None)
        self.credits  = self.load_credits()
        self.stats    = self.load_stats()
        self.car_data = self.load_car_data()
        self.load_options()   # map_pixel_size などを復元
        # カスタマイズ画面の選択状態
        self.cust_tab      = 0   # 0=カラー, 1=エンジン, 2=ブレーキ, 3=軽量化
        self.cust_color_sel = 0  # 選択中のカラーインデックス
        self.cust_msg      = ""
        self.cust_msg_timer = 0
        self.reset()
        self._maker_reset()

        pyxel.run(self.update, self.draw)

    # ------------------------------------------------------------------
    # コースユーティリティ
    # ------------------------------------------------------------------

    def _course_key(self, idx=None):
        """ベストタイム保存用キー (コース名ベース, 削除でズレない)"""
        i = self.selected_course if idx is None else idx
        return f"best_lap_{self.COURSES[i]['name']}"

    # ── カスタムコース保存/読み込み/削除 ────────────────────────────
    def _load_custom_courses(self):
        """カスタムコースを読んで COURSES に追記 (Web/PC両対応)"""
        if IS_WEB:
            try:
                data = js.window.localStorage.getItem("highway_racer_custom_courses")
                if data:
                    customs = json.loads(data)
                    self._apply_custom_courses(customs)
            except Exception:
                pass
        else:
            if not os.path.exists(self.custom_courses_file):
                return
            try:
                with open(self.custom_courses_file, 'r', encoding='utf-8') as f:
                    customs = json.load(f)
                self._apply_custom_courses(customs)
            except Exception:
                pass

    def _apply_custom_courses(self, customs):
        """読み込んだデータをリストに反映する共通処理"""
        existing = {c['name'] for c in self.COURSES}
        for cd in customs:
            if cd['name'] not in existing:
                if 'night_remap' in cd:
                    cd['night_remap'] = {int(k): v for k, v in cd['night_remap'].items()}
                cd['control_points'] = [tuple(p) for p in cd['control_points']]
                cd['checkpoints']    = [tuple(p) for p in cd['checkpoints']]
                cd['start_pos']      = tuple(cd['start_pos'])
                cd['start_angle']    = float(cd.get('start_angle', 0.0))
                cd['start_line']     = list(cd['start_line'])
                cd['walls']          = cd.get('walls', [])  # 壁データを保持
                self.COURSES.append(cd)
                existing.add(cd['name'])

    def _save_custom_courses(self):
        """COURSES[4:] を保存 (Web/PC両対応)"""
        customs = self.COURSES[4:]
        if IS_WEB:
            try:
                js.window.localStorage.setItem("highway_racer_custom_courses", json.dumps(customs))
            except Exception:
                pass
        else:
            try:
                with open(self.custom_courses_file, 'w', encoding='utf-8') as f:
                    json.dump(customs, f, ensure_ascii=False, indent=2)
            except Exception:
                pass

    def _delete_custom_course(self, idx):
        """指定インデックスのカスタムコースを削除"""
        if idx < 4:
            return
        name = self.COURSES[idx]['name']
        key    = self._course_key(idx)
        ta_key = self._ta_ranking_key(idx)
        self.best_times.pop(key, None)
        self.best_times.pop(ta_key, None)

        # 共通のベストタイム保存処理を呼ぶ
        self.save_best_times()

        self.COURSES.pop(idx)
        self.course_data.pop(idx)
        self._save_custom_courses()

        if self.selected_course >= len(self.COURSES):
            self.selected_course = len(self.COURSES) - 1
        self._build_map(self.selected_course)
        ranking = self.get_ta_ranking()
        self.best_lap_time = ranking[0] if ranking else self.best_times.get(self._course_key(), None)

    def _calc_smooth_points(self, control_points):
        """制御点からCatmull-Romスプラインで滑らかな点列を生成して返す"""
        def catmull_rom(p0, p1, p2, p3, t):
            t2 = t * t
            t3 = t2 * t
            f1 = -0.5 * t3 + t2 - 0.5 * t
            f2 = 1.5 * t3 - 2.5 * t2 + 1.0
            f3 = -1.5 * t3 + 2.0 * t2 + 0.5 * t
            f4 = 0.5 * t3 - 0.5 * t2
            return (
                p0[0] * f1 + p1[0] * f2 + p2[0] * f3 + p3[0] * f4,
                p0[1] * f1 + p1[1] * f2 + p2[1] * f3 + p3[1] * f4
            )
        smooth_points = []
        n = len(control_points)
        for i in range(n):
            p0 = control_points[(i - 1) % n]
            p1 = control_points[i]
            p2 = control_points[(i + 1) % n]
            p3 = control_points[(i + 2) % n]
            for j in range(15):
                t = j / 15.0
                smooth_points.append(catmull_rom(p0, p1, p2, p3, t))
        return smooth_points

    def _build_map(self, course_idx):
        """指定コースのマップデータをイメージバンク1に描画する"""
        cd = self.COURSES[course_idx]
        smooth_points = self.course_data[course_idx]["smooth_points"]

        # 背景(芝/土)で塗りつぶす
        pyxel.image(1).rect(0, 0, 256, 256, cd["col_ground"])

        # map_pixel_size: 何ピクセル分の間隔でcircを打つか（1=精細, 4=粗い）
        step = getattr(self, "map_pixel_size", 2)

        def draw_path(pts, r, col):
            for i in range(len(pts) - 1):
                x1, y1 = pts[i]
                x2, y2 = pts[i + 1]
                dist = max(1, math.hypot(x2 - x1, y2 - y1))
                n = max(1, int(dist / step))
                for j in range(n + 1):
                    px = x1 + (x2 - x1) * (j / n)
                    py = y1 + (y2 - y1) * (j / n)
                    pyxel.image(1).circ(px, py, r, col)

        draw_path(smooth_points, cd["road_outer"], cd["col_outer"])
        draw_path(smooth_points, cd["road_mid"],   cd["col_mid"])
        draw_path(smooth_points, cd["road_inner"], cd["col_inner"])

        # ミニマップ用コース線をキャッシュ（毎フレーム描画を回避）
        map_scale = 48 / 256.0
        pts = smooth_points
        self._minimap_lines = [
            (pts[i][0] * map_scale, pts[i][1] * map_scale,
             pts[(i + 1) % len(pts)][0] * map_scale,
             pts[(i + 1) % len(pts)][1] * map_scale)
            for i in range(len(pts))
        ]

        # スタート/ゴールライン描画
        # 新形式: [cx, cy, angle, road_outer] → 角度付き白線、道幅内のみ
        # 旧形式: [x, y, w, h] → 固定矩形（後方互換）
        sl = cd["start_line"]
        if len(sl) == 4 and isinstance(sl[2], float) and sl[2] <= math.pi * 2 + 0.01 and sl[3] <= 20:
            cx_, cy_, angle_, road_outer_ = sl
            perp_ = angle_ + math.pi / 2
            # 道幅内の両端まで1px刻みで白線を描く
            for t_px in range(-int(road_outer_), int(road_outer_) + 1):
                bx_ = cx_ + math.cos(perp_) * t_px
                by_ = cy_ + math.sin(perp_) * t_px
                # 進行方向に3px幅（中央±1）
                for d_ in range(-1, 2):
                    px_ = int(bx_ + math.cos(angle_) * d_)
                    py_ = int(by_ + math.sin(angle_) * d_)
                    if 0 <= px_ < 256 and 0 <= py_ < 256:
                        pyxel.image(1).pset(px_, py_, 7)
        else:
            pyxel.image(1).rect(int(sl[0]), int(sl[1]), int(sl[2]), int(sl[3]), 7)

        # smooth_pointsをゲームロジックから参照できるようにする
        self.smooth_points = smooth_points
        self.racing_line   = self.course_data[course_idx]["racing_line"]

        # 壁をマップ画像に描画（色13=ダークグレー、太さ2px）
        WALL_COL = 13
        for w in cd.get("walls", []):
            x1, y1, x2, y2 = w["x1"], w["y1"], w["x2"], w["y2"]
            length = max(1, math.hypot(x2 - x1, y2 - y1))
            steps  = max(1, int(length))
            for k in range(steps + 1):
                t  = k / steps
                wx = x1 + (x2 - x1) * t
                wy = y1 + (y2 - y1) * t
                for ox, oy in [(0,0),(1,0),(0,1),(1,1)]:
                    px_, py_ = int(wx) + ox, int(wy) + oy
                    if 0 <= px_ < 256 and 0 <= py_ < 256:
                        pyxel.image(1).pset(px_, py_, WALL_COL)

    # ------------------------------------------------------------------
    # セーブ/ロード
    # ------------------------------------------------------------------

    def _calc_racing_line(self, smooth_points, road_outer):
        """アウトインアウトのレーシングラインを生成。道幅内に収まるよう制限する。"""
        n = len(smooth_points)
        window = 5
        curvatures = []
        for i in range(n):
            p0 = smooth_points[(i - window) % n]
            p1 = smooth_points[i]
            p2 = smooth_points[(i + window) % n]
            dx1 = p1[0]-p0[0]; dy1 = p1[1]-p0[1]
            dx2 = p2[0]-p1[0]; dy2 = p2[1]-p1[1]
            cross = dx1*dy2 - dy1*dx2
            m1 = math.hypot(dx1, dy1); m2 = math.hypot(dx2, dy2)
            if m1 > 0 and m2 > 0:
                cos_a = max(-1.0, min((dx1*dx2+dy1*dy2)/(m1*m2), 1.0))
                sign = 1.0 if cross >= 0 else -1.0
                curvatures.append(sign * math.acos(cos_a))
            else:
                curvatures.append(0.0)

        # 平滑化（前後 k 点の移動平均）
        k = 14
        smoothed = []
        for i in range(n):
            smoothed.append(sum(curvatures[(i+j-k//2) % n] for j in range(k)) / k)

        max_curv = max(abs(c) for c in smoothed) or 1.0
        # オフセット上限を道幅の 40% に抑えてダートに出ないようにする
        max_offset = road_outer * 0.40

        racing_line = []
        for i in range(n):
            px, py = smooth_points[i]
            nx_i = (i + 1) % n
            dx = smooth_points[nx_i][0] - px
            dy = smooth_points[nx_i][1] - py
            length = math.hypot(dx, dy)
            if length > 0:
                nx = -dy / length
                ny =  dx / length
            else:
                nx = ny = 0.0
            norm_c = smoothed[i] / max_curv
            offset = -norm_c * max_offset
            racing_line.append((px + nx * offset, py + ny * offset))
        return racing_line

    def load_best_times(self):
        if IS_WEB:
            try:
                data = js.window.localStorage.getItem("highway_racer_best_times")
                if data:
                    return json.loads(data)
            except Exception:
                pass
            return {}
        else:
            if os.path.exists(self.save_file):
                try:
                    with open(self.save_file, "r") as f:
                        return json.load(f)
                except Exception:
                    pass
            return {}

    def save_best_times(self):
        if IS_WEB:
            try:
                js.window.localStorage.setItem("highway_racer_best_times", json.dumps(self.best_times))
            except Exception:
                pass
        else:
            try:
                with open(self.save_file, "w") as f:
                    json.dump(self.best_times, f)
            except Exception:
                pass

    # ── ゴーストデータ保存/読み込み ──────────────────────────────────
    def _ghost_file_path(self):
        name = self.COURSES[self.selected_course]["name"].replace(" ", "_")
        return os.path.join(os.path.dirname(self.save_file), f"ghost_{name}.json")

    def save_ghost(self, frames):
        """ベストラップのゴーストデータを保存。
        毎フレームデータをそのまま保存（最大6000フレーム≒200秒分）。
        サイズが大きすぎる場合のみ間引く。"""
        SAMPLE = 1  # 原則1フレームごと保存
        # 6000フレーム超なら間引く（異常に長いラップへの安全弁）
        if len(frames) > 6000:
            SAMPLE = 2
        sampled = frames[::SAMPLE]
        data = {"frames": sampled, "sample": SAMPLE}
        if IS_WEB:
            try:
                key = f"highway_racer_ghost_{self.COURSES[self.selected_course]['name']}"
                js.window.localStorage.setItem(key, json.dumps(data))
            except Exception:
                pass
        else:
            try:
                with open(self._ghost_file_path(), "w") as f:
                    json.dump(data, f)
            except Exception:
                pass

    def load_ghost(self):
        """ゴーストデータを読み込む。{"frames":[...],"sample":N} 形式、または旧形式リストを返す。
        戻り値: (frames_list, sample_rate) のタプル。データなしは ([], 1)。"""
        raw = None
        if IS_WEB:
            try:
                key = f"highway_racer_ghost_{self.COURSES[self.selected_course]['name']}"
                data = js.window.localStorage.getItem(key)
                if data:
                    raw = json.loads(data)
            except Exception:
                pass
        else:
            path = self._ghost_file_path()
            if os.path.exists(path):
                try:
                    with open(path, "r") as f:
                        raw = json.load(f)
                except Exception:
                    pass
        if raw is None:
            return [], 1
        # 新形式: dict with "frames" key
        if isinstance(raw, dict) and "frames" in raw:
            return raw["frames"], int(raw.get("sample", 1))
        # 旧形式: list（5フレームサンプリング済み）
        if isinstance(raw, list):
            return raw, 5
        return [], 1

    # ================================================================
    # 共有ユーティリティ
    # ================================================================

    def _online_broadcast_settings(self):
        """ホストが現在の設定をルーム全員に送信する。"""
        if self.online_client and self.online_client.connected:
            self.online_client.send_priority({
                "type":       "settings",
                "player_id":  self.online_my_id,
                "course_idx": self.selected_course,
                "night":      self.is_night_mode,
                "laps":       self.goal_laps,
                "course_name": self.COURSES[self.selected_course]["name"],
            })

    def _set_share_msg(self, msg, frames=150):
        self._share_msg = msg
        self._share_msg_timer = frames

    def _make_share_html(self, json_str, title, hint_lines):
        """データをBase64埋め込みのHTMLに変換して返す。
        ブラウザで開けばJSONの表示・コピー・ダウンロードができる。
        OS問わず（Windows / Mac / Linux）どのブラウザでも動く。"""
        b64 = base64.b64encode(json_str.encode("utf-8")).decode()
        hint_html = "".join(f"<li>{h}</li>" for h in hint_lines)
        fname = title.replace(" ", "_") + ".json"
        return f"""<!DOCTYPE html>
<html lang="ja"><head><meta charset="UTF-8">
<title>Highway Racer &#8211; {title}</title>
<style>
  body{{margin:0;background:#111;color:#eee;font-family:monospace;padding:24px}}
  h2{{color:#fd0;margin:0 0 8px}}
  ul{{color:#aaa;font-size:13px;margin:4px 0 16px;padding-left:20px}}
  textarea{{display:block;width:100%;box-sizing:border-box;height:260px;
           background:#1a1a1a;color:#4f4;border:1px solid #444;
           padding:8px;font-size:11px;resize:vertical}}
  .btns{{margin:10px 0}}
  button{{padding:8px 20px;margin-right:8px;background:#222;color:#eee;
         border:1px solid #666;cursor:pointer;font-size:14px;border-radius:4px}}
  button:hover{{background:#444}}
  #msg{{color:#fd0;font-size:13px;margin-top:6px;min-height:18px}}
</style></head><body>
<h2>&#127947; Highway Racer &mdash; {title}</h2>
<ul>{hint_html}</ul>
<textarea id="ta" readonly></textarea>
<div class="btns">
  <button onclick="copy()">&#128203; JSONをコピー</button>
  <button onclick="dl()">&#128190; .jsonとして保存</button>
</div>
<div id="msg"></div>
<script>
const data = atob("{b64}");
document.getElementById("ta").value = data;
function copy(){{
  navigator.clipboard.writeText(data).then(
    ()=>{{document.getElementById("msg").textContent="コピーしました！"}},
    ()=>{{document.getElementById("ta").select();document.execCommand("copy");
         document.getElementById("msg").textContent="コピーしました（フォールバック）"}}
  );
}}
function dl(){{
  const a=document.createElement("a");
  a.href="data:application/json;charset=utf-8,"+encodeURIComponent(data);
  a.download="{fname}";a.click();
}}
</script></body></html>"""

    # ── ゴースト エクスポート / インポート ────────────────────────────

    def export_ghost(self):
        """現在コースのゴーストをJSON + HTMLファイルに書き出す。"""
        if IS_WEB:
            self._set_share_msg("WEB版ではエクスポート非対応"); return
        frames, sample = self.load_ghost()
        if not frames:
            self._set_share_msg("ゴーストデータがありません"); return
        cd = self.COURSES[self.selected_course]
        payload = json.dumps({
            "type": "ghost", "version": 1,
            "course": cd["name"], "sample": sample, "frames": frames,
        }, separators=(',', ':'))
        default = f"ghost_{cd['name'].replace(' ','_')}.json"
        path = _ask_save("ゴーストを保存", default,
                         (("JSON files", "*.json"), ("All files", "*.*")))
        if not path:
            self._set_share_msg("キャンセルしました", 60); return
        try:
            with open(path, "w", encoding="utf-8") as f: f.write(payload)
            # 同フォルダにHTMLも出力
            html_path = os.path.splitext(path)[0] + ".html"
            hint = [
                "このHTMLをブラウザで開くとJSONの確認・ダウンロードができます",
                "受け取った .json を相手の claude.py と同じフォルダに置き",
                "コース選択画面でタイムアタックモードにして [L] キーでインポート",
            ]
            html = self._make_share_html(payload, f"Ghost – {cd['name']}", hint)
            with open(html_path, "w", encoding="utf-8") as f: f.write(html)
            self._set_share_msg(f"エクスポート完了: {os.path.basename(path)}")
        except Exception as e:
            self._set_share_msg(f"エクスポート失敗: {e}")

    def import_ghost(self):
        """JSONファイルから他人のゴーストを読み込み、現在コースに上書きする。"""
        if IS_WEB:
            self._set_share_msg("WEB版ではインポート非対応"); return
        path = _ask_open("ゴーストを開く",
                         (("JSON files", "*.json"), ("All files", "*.*")))
        if not path:
            self._set_share_msg("キャンセルしました", 60); return
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if data.get("type") != "ghost":
                self._set_share_msg("ゴーストファイルではありません"); return
            cd = self.COURSES[self.selected_course]
            if data.get("course") != cd["name"]:
                self._set_share_msg(f"コース不一致: {data.get('course','')}"); return
            save_data = {"frames": data["frames"], "sample": data.get("sample", 1)}
            with open(self._ghost_file_path(), "w", encoding="utf-8") as f:
                json.dump(save_data, f)
            self.ghost_data, self.ghost_sample = self.load_ghost()
            self._set_share_msg("ゴーストをインポートしました！")
        except Exception as e:
            self._set_share_msg(f"インポート失敗: {e}")

    # ── コース エクスポート / インポート ─────────────────────────────

    def export_course(self):
        """選択中コースをJSON + HTMLに書き出す。"""
        if IS_WEB:
            self._set_share_msg("WEB版ではエクスポート非対応"); return
        cd = self.COURSES[self.selected_course]
        # tuple → list に変換してJSONシリアライズ可能にする
        export_cd = dict(cd)
        export_cd["control_points"] = [list(p) for p in cd["control_points"]]
        export_cd["checkpoints"]    = [list(p) for p in cd["checkpoints"]]
        export_cd["start_pos"]      = list(cd["start_pos"])
        export_cd["walls"]          = cd.get("walls", [])
        payload = json.dumps({
            "type": "course", "version": 1, "course": export_cd,
        }, separators=(',', ':'), ensure_ascii=False)
        default = f"course_{cd['name'].replace(' ','_')}.json"
        path = _ask_save("コースを保存", default,
                         (("JSON files", "*.json"), ("All files", "*.*")))
        if not path:
            self._set_share_msg("キャンセルしました", 60); return
        try:
            with open(path, "w", encoding="utf-8") as f: f.write(payload)
            html_path = os.path.splitext(path)[0] + ".html"
            hint = [
                "このHTMLをブラウザで開くとJSONの確認・ダウンロードができます",
                "受け取った .json を claude.py と同じフォルダに置いて",
                "コース選択画面で [I] キーを押してインポート",
            ]
            html = self._make_share_html(payload, f"Course – {cd['name']}", hint)
            with open(html_path, "w", encoding="utf-8") as f: f.write(html)
            self._set_share_msg(f"エクスポート完了: {os.path.basename(path)}")
        except Exception as e:
            self._set_share_msg(f"エクスポート失敗: {e}")

    def import_course(self):
        """JSONファイルからコースを読み込んでカスタムコースとして追加する。"""
        if IS_WEB:
            self._set_share_msg("WEB版ではインポート非対応"); return
        path = _ask_open("コースを開く",
                         (("JSON files", "*.json"), ("All files", "*.*")))
        if not path:
            self._set_share_msg("キャンセルしました", 60); return
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if data.get("type") != "course":
                self._set_share_msg("コースファイルではありません"); return
            cd_raw = data["course"]
            if "night_remap" in cd_raw:
                cd_raw["night_remap"] = {int(k): v for k, v in cd_raw["night_remap"].items()}
            cd_raw["control_points"] = [tuple(p) for p in cd_raw["control_points"]]
            cd_raw["checkpoints"]    = [tuple(p) for p in cd_raw["checkpoints"]]
            cd_raw["start_pos"]      = tuple(cd_raw["start_pos"])
            cd_raw["start_angle"]    = float(cd_raw.get("start_angle", 0.0))
            cd_raw["start_line"]     = list(cd_raw["start_line"])
            cd_raw["walls"]          = cd_raw.get("walls", [])
            existing = {c["name"] for c in self.COURSES}
            if cd_raw["name"] in existing:
                self._set_share_msg(f"既に存在: {cd_raw['name']}"); return
            self.COURSES.append(cd_raw)
            smooth = self._calc_smooth_points(cd_raw["control_points"])
            rl     = self._calc_racing_line(smooth, cd_raw["road_outer"])
            self.course_data.append({"smooth_points": smooth, "racing_line": rl})
            self._save_custom_courses()
            self.selected_course = len(self.COURSES) - 1
            self._build_map(self.selected_course)
            self._set_share_msg(f"インポート完了: {cd_raw['name']}")
        except Exception as e:
            self._set_share_msg(f"インポート失敗: {e}")

    # ── タイムアタックランキング（TOP5）ヘルパー ──────────────────────

    def _ta_ranking_key(self, idx=None):
        i = self.selected_course if idx is None else idx
        return f"ta_ranking_{self.COURSES[i]['name']}"

    def get_ta_ranking(self, idx=None):
        """コースのタイムアタックランキング上位5件リストを返す"""
        return self.best_times.get(self._ta_ranking_key(idx), [])

    def add_ta_record(self, lap_time):
        """タイムアタック記録を追加し上位5件を保持。新記録ならTrue返す"""
        key = self._ta_ranking_key()
        ranking = self.best_times.get(key, [])
        old_best = ranking[0] if ranking else None
        ranking.append(lap_time)
        ranking.sort()
        ranking = ranking[:5]
        self.best_times[key] = ranking
        self.best_lap_time = ranking[0]
        self.best_times[self._course_key()] = ranking[0]
        self.save_best_times()
        return (old_best is None or lap_time < old_best)

    def load_credits(self):
        if IS_WEB:
            try:
                data = js.window.localStorage.getItem("highway_racer_credits")
                if data:
                    return int(json.loads(data)) + self.DEBUG_INITIAL_CREDITS
            except Exception:
                pass
            return self.DEBUG_INITIAL_CREDITS
        else:
            if os.path.exists(self.credits_file):
                try:
                    with open(self.credits_file, "r") as f:
                        return int(json.load(f)) + self.DEBUG_INITIAL_CREDITS
                except Exception:
                    pass
            return self.DEBUG_INITIAL_CREDITS

    def save_credits(self):
        if IS_WEB:
            try:
                js.window.localStorage.setItem("highway_racer_credits", json.dumps(self.credits))
            except Exception:
                pass
        else:
            try:
                with open(self.credits_file, "w") as f:
                    json.dump(self.credits, f)
            except Exception:
                pass

    def load_stats(self):
        default = {
            "race_count":      0,   # レース参加回数
            "first_count":     0,   # 1位になった回数
            "total_credits":   0,   # 総獲得クレジット（使用前の累計）
            "total_distance":  0.0, # 総走行距離（ワールド単位）
            "total_frames":    0,   # 総走行フレーム数（30fps換算で秒数計算）
        }
        if IS_WEB:
            try:
                data = js.window.localStorage.getItem("highway_racer_stats")
                if data:
                    loaded = json.loads(data)
                    default.update(loaded)
            except Exception:
                pass
        else:
            if os.path.exists(self.stats_file):
                try:
                    with open(self.stats_file, "r") as f:
                        loaded = json.load(f)
                        default.update(loaded)
                except Exception:
                    pass
        return default

    def save_stats(self):
        if IS_WEB:
            try:
                js.window.localStorage.setItem("highway_racer_stats", json.dumps(self.stats))
            except Exception:
                pass
        else:
            try:
                with open(self.stats_file, "w") as f:
                    json.dump(self.stats, f)
            except Exception:
                pass

    def load_options(self):
        """map_pixel_size などのオプションをロードする"""
        default = {"map_pixel_size": 2, "wheel_sensitivity": 5}
        if IS_WEB:
            try:
                data = js.window.localStorage.getItem("highway_racer_options")
                if data:
                    default.update(json.loads(data))
            except Exception:
                pass
        else:
            if os.path.exists(self.options_file):
                try:
                    with open(self.options_file, "r") as f:
                        default.update(json.load(f))
                except Exception:
                    pass
        self.map_pixel_size      = max(1, min(4,  int(default.get("map_pixel_size", 2))))
        self.wheel_sensitivity   = max(1, min(10, int(default.get("wheel_sensitivity", 5))))

    def save_options(self):
        data = {"map_pixel_size": self.map_pixel_size,
                "wheel_sensitivity": self.wheel_sensitivity}
        if IS_WEB:
            try:
                js.window.localStorage.setItem("highway_racer_options", json.dumps(data))
            except Exception:
                pass
        else:
            try:
                with open(self.options_file, "w") as f:
                    json.dump(data, f)
            except Exception:
                pass

    # カラーパレット定義（pyxelカラー番号, 表示名, 購入済みフラグ）
    CAR_COLORS = [
        {"col": 195, "name": "WHITE",   "price": 0},    # デフォルト無料
        {"col": 12,  "name": "CYAN",    "price": 500},
        {"col": 10,  "name": "YELLOW",   "price": 500},
        {"col": 11,  "name": "GREEN",  "price": 500},
        {"col": 14,  "name": "PINK",    "price": 500},
        {"col": 8,   "name": "RED",     "price": 500},
        {"col": 9,   "name": "ORANGE",  "price": 500},
        {"col": 6,   "name": "BLUE",    "price": 500},
    ]

    def load_car_data(self):
        default = {
            "engine_lv":  1,
            "brake_lv":   1,
            "weight_lv":  1,
            "owned_colors": [0],   # 購入済みカラーインデックスリスト（0=WHITE無料）
            "color_idx":  0,
        }
        if IS_WEB:
            try:
                data = js.window.localStorage.getItem("highway_racer_car_data")
                if data:
                    loaded = json.loads(data)
                    default.update(loaded)
            except Exception:
                pass
        else:
            if os.path.exists(self.car_data_file):
                try:
                    with open(self.car_data_file, "r") as f:
                        loaded = json.load(f)
                        default.update(loaded)
                except Exception:
                    pass
        # カラーを反映
        idx = default.get("color_idx", 0)
        if 0 <= idx < len(self.CAR_COLORS):
            self.car_color = self.CAR_COLORS[idx]["col"]
        return default

    def save_car_data(self):
        self.car_data["color_idx"] = self.cust_color_sel
        if IS_WEB:
            try:
                js.window.localStorage.setItem("highway_racer_car_data", json.dumps(self.car_data))
            except Exception:
                pass
        else:
            try:
                with open(self.car_data_file, "w") as f:
                    json.dump(self.car_data, f)
            except Exception:
                pass

    def get_perf_mult(self):
        """
        エンジン/ブレーキ/軽量化レベルから性能乗数を返す。
        Lv1=0.6, Lv10=1.2 の線形スケール。
        軽量化はエンジン・ブレーキ・ハンドリング全てに追加乗算。
        """
        def lv_to_mult(lv):
            # Lv1→0.60, Lv10→1.20  (step = 0.60/9 ≈ 0.0667)
            return 0.60 + (lv - 1) * (0.60 / 9.0)

        eng = lv_to_mult(self.car_data["engine_lv"])
        brk = lv_to_mult(self.car_data["brake_lv"])
        wgt = lv_to_mult(self.car_data["weight_lv"])

        # エンジン強化 → ハンドリングは反比例（最大-25%）
        eng_handling_pen = 1.0 - (self.car_data["engine_lv"] - 1) * 0.025

        return {
            "accel":    eng * wgt,            # 加速力
            "max_vel":  eng * wgt,            # 最高速
            "brake":    brk * wgt,            # ブレーキ力
            "handling": eng_handling_pen * wgt,  # ハンドリング
            "grip":     wgt,                  # グリップ
        }

    # ------------------------------------------------------------------
    # リセット
    # ------------------------------------------------------------------

    def reset(self):
        self.setup_sounds()
        self.is_respawning = False
        self.respawn_timer = 0
        self.respawn_pos_x = 0.0
        self.respawn_pos_y = 0.0
        self.respawn_angle = 0.0
        self.out_frames = 0         # コースアウト継続フレーム数
        self.gear = 0
        self.rpm = 0
        self.display_rpm = 0
        self.is_reverse   = False  # リバースギア中フラグ
        self.reverse_wait = 0      # AT: 停車後のバックギア移行待ちフレーム数

        cd = self.COURSES[self.selected_course]
        self.car_world_x = cd["start_pos"][0]
        self.car_world_y = cd["start_pos"][1]
        self.car_angle   = cd["start_angle"]
        self.car_velocity = 0
        self.velocity = 0
        self.kilometer = 0
        self.u = 49
        self.w = 0
        self.steer_input = 0.0   # ハンドル位置 -1.0(左)〜0.0(中)〜1.0(右)
        self.vx = 0.0          # ワールド座標X方向の速度
        self.vy = 0.0          # ワールド座標Y方向の速度
        self.slip_angle   = 0.0   # スリップ角（ラジアン）
        self.is_sliding      = False  # スライド中フラグ（エフェクト用）
        self.is_traction_loss = False  # トラクション抜けフラグ
        self.is_understeer = False  # アンダーステア中
        self.is_oversteer  = False  # オーバーステア中

        # --- 進行度トラッキング変数のリセット（ラバーバンド引き継ぎ防止）---
        self.car_lap      = 0
        self.car_prev_idx = 0

        # --- ラップ計測用の変数 ---
        self.current_lap = 1
        self.lap_frame_count = 0
        self.last_lap_time = 0.0
        self.checkpoints = cd["checkpoints"]
        self.next_cp_index = 0

        self.is_goal = False
        self.is_braking = False
        self.is_out = False
        self.is_new_record = False
        self.confetti = []
        
        self.dirt_particles  = []    # 土煙エフェクト用
        self.spark_particles = []    # 衝突スパークエフェクト用
        
        self.is_boosting = False
        self.boost_timer = 0
        self.boost_cooldown = 0
        self.is_rocket_start = False
        self.rocket_timer = 0
        self.rocket_text_timer = 0
        self.is_stalled = False
        self.stall_timer = 0
        self.is_spinning = False
        self.spin_timer = 0
        self.shake_amount = 0
        self.grass_shake = 0
        self.start_timer = 200
        self.auto_gear_cooldown = 0
        self.current_rank = 1
        self.car_progress = 0
        self.car_lap = 0
        self.car_prev_idx = 0
        self.goal_auto_drive = False
        self.goal_auto_idx = 0
        self.clouds = []
        while len(self.clouds) < 5:
            c_type = random.choice([0, 1])
            cw, ch, u, v = (45, 15, 0, 0) if c_type == 0 else (30, 20, 0, 15)
            self.clouds.append({
                "x": random.uniform(0, pyxel.width),
                "y": random.uniform(5, 40),
                "depth": random.uniform(0.1, 0.8),
                "u": u, "v": v,
                "orig_w": cw, "orig_h": ch,
                "speed_factor": random.uniform(0.05, 0.1)
            })
        # smooth_pointsからスタート地点に最も近いインデックスを求める
        smooth_pts = self.course_data[self.selected_course]["smooth_points"]
        sp = cd["start_pos"]
        closest_start_idx = min(range(len(smooth_pts)),
                                key=lambda i: math.hypot(smooth_pts[i][0] - sp[0],
                                                         smooth_pts[i][1] - sp[1]))
        n_pts = len(smooth_pts)

        def get_course_pos_and_angle(idx):
            idx = idx % n_pts
            cx, cy = smooth_pts[idx]
            nx, ny = smooth_pts[(idx + 1) % n_pts]
            angle = math.atan2(ny - cy, nx - cx)
            return cx, cy, angle

        # ライバルカーの生成（レースモード時のみ）
        self.rivals = []
        colors = [12, 10, 11, 14, 8, 9, 6, 13, 15, 4, 3]
        num_rivals = 0 if self.is_time_attack else getattr(self, 'num_rivals', 3)
        if getattr(self, 'online_client', None) and self.online_client.connected:
            num_rivals = 0   # オンラインモードはライバルなし
        step = 6
        for i in range(num_rivals):
            rival_idx = (closest_start_idx - step * (num_rivals - i)) % n_pts
            rx, ry, ra = get_course_pos_and_angle(rival_idx)
            rival = RivalCar(colors[i % len(colors)], (rx, ry), ra)
            rival.prev_idx = rival_idx
            rival.progress = rival_idx
            self.rivals.append(rival)

        # ── ライバル個別性能スケール割り当て ──
        # rivals[0] が最前列、rivals[-1] が最後尾
        # 基本：前から 1.0 → 0.7 に線形低下
        # ごぼう抜き枠：約15%の確率で後方ライバルに先頭相当の高性能を付与
        for i, rival in enumerate(self.rivals):
            if num_rivals <= 1:
                base_scale = 1.0
            else:
                t = i / (num_rivals - 1)          # 0.0(先頭)〜1.0(最後尾)
                base_scale = 1.0 - t * 0.30       # 1.0〜0.70 に線形低下
            # 後方ライバル（後半グリッド）に約15%の確率で強いライバルを混入
            if i >= num_rivals // 2 and random.random() < 0.15:
                base_scale = random.uniform(0.92, 1.0)   # 先頭集団相当
            rival.perf_scale = round(base_scale, 3)

        # 自車配置：タイムアタックはスタートライン、オンラインはグリッド番号順、レースは最後尾
        is_online = (getattr(self, 'online_client', None) and
                     getattr(self.online_client, 'connected', False))
        if self.is_time_attack:
            px, py, pa = get_course_pos_and_angle(closest_start_idx)
            self.car_progress = closest_start_idx
            self.car_prev_idx = closest_start_idx
        elif is_online:
            # グリッド番号 0=ホスト(先頭) 〜 3=最後尾
            grid       = getattr(self, 'online_grid_idx', 0)
            total      = len(getattr(self, 'online_peers', {})) + 1
            # 先頭(grid=0)がスタートラインの1step後ろ、以降6stepずつ下がる
            player_idx = (closest_start_idx - step * (total - grid)) % n_pts
            px, py, pa = get_course_pos_and_angle(player_idx)
            self.car_progress = player_idx
            self.car_prev_idx = player_idx
        else:
            player_idx = (closest_start_idx - step * (num_rivals + 1)) % n_pts
            px, py, pa = get_course_pos_and_angle(player_idx)
            self.car_progress = player_idx
            self.car_prev_idx = player_idx
        self.car_world_x = px
        self.car_world_y = py
        self.car_angle   = pa

        self.goal_rank = 1  # ゴール時の最終順位
        self._rank_candidate = 1
        self._rank_hold = 0
        self.collision_count = 0   # 衝突回数（クリーンレース判定用）
        self.online_finish_order = []  # オンラインゴール順 [(pid, label), ...]
        self.total_race_time = 0.0     # レース開始からの総時間(秒)

        # ゴースト初期化（タイムアタック時のみ）
        self.ghost_record    = []
        self.ghost_frame_idx = 0
        self.ghost_sample    = 1    # ゴーストのサンプリングレート
        if self.is_time_attack:
            frames, sample = self.load_ghost()
            self.ghost_data   = frames
            self.ghost_sample = sample
        else:
            self.ghost_data   = []
            self.ghost_sample = 1
        self.prize_amount = 0      # 獲得賞金
        self.prize_bonus = 0       # クリーンレースボーナス
        self.prize_display = 0     # アニメーション表示用（徐々に増加）
        self.prize_anim_timer = 0  # 賞金演出タイマー
        self.prize_anim_phase = 0  # 演出フェーズ (0=待機, 1=基本賞金加算中, 2=ボーナス加算中, 3=完了)
        self.session_distance = 0.0   # 今レースの走行距離
        self.session_frames   = 0     # 今レースの走行フレーム数

        # スリップストリーム
        self.slipstream_timer  = 0     # 他車の後ろにいる継続フレーム数
        self.slipstream_active = False # スリップストリーム発動中
        self.slipstream_particles = [] # 風エフェクトパーティクル

    def setup_sounds(self):
        pyxel.sounds[0].set("c1a0 ", "n", "6", "n", 2)
        pyxel.sounds[0].volumes[0] = 4
        pyxel.sounds[1].set("c3", "p", "2", "n", 5)
        pyxel.sounds[2].set("c2e2g2c3", "s", "6", "f", 10)
        pyxel.sounds[3].set("c3e3g3b3 c3e3g3b3 d3f#3a3c#4 d3f#3a3c#4 g3r g3r g4", "s", "6", "f", 7)
        pyxel.sounds[4].set("c1c1c1", "n", "7", "f", 20)
        pyxel.sounds[5].set("c4d4e4g4","s","5","v",5)

    def setup_custom_palette(self):
        original_palette = pyxel.colors.to_list()
        step_val = 0x33
        new_colors = [
            ((i % 6) * step_val) +
            (((i // 6) % 6) * step_val) * 0x100 +
            (((i // 36) % 6) * step_val) * 0x10000
            for i in range(1, 216)
        ]
        combined_palette = original_palette + new_colors
        pyxel.colors.from_list(combined_palette[:230])

    # ------------------------------------------------------------------
    # update
    # ------------------------------------------------------------------

    def update(self):
        # ── ハンコン仮想キーフラグ（ボタン番号と状態別の役割）──
        # Btn 5 → SPACE    （全画面で決定）
        # Btn 4 → ESC      （レース中＝無効、ポーズ中＝ESC、その他メニュー＝ESC）
        # Btn 0 → Q        （全画面。ただしレース中はシフトダウンに使わない）
        # Btn 1 → E        （全画面。ただしレース中はシフトアップに使わない）
        # 十字キー → UP/DOWN/LEFT/RIGHT（全画面）
        is_play  = (getattr(self, 'state', -1) == getattr(self, 'STATE_PLAY',  2))
        is_pause = (getattr(self, 'state', -1) == getattr(self, 'STATE_PAUSE', 3))

        if _HAS_JOY:
            _pg.event.pump()

            # エッジ検出ヘルパー（前フレームと比較して「今押した」を返す）
            def _edge(btn_idx, attr):
                now = _joy_btn(btn_idx)
                fired = now and not getattr(self, attr, False)
                setattr(self, attr, now)
                return fired

            b5_edge = _edge(5, '_jprev_b5')   # SPACE
            b4_edge = _edge(4, '_jprev_b4')   # ESC (条件付き)
            b0_edge = _edge(0, '_jprev_b0')   # Q
            b1_edge = _edge(1, '_jprev_b1')   # E

            # 十字キー
            _hx, _hy = _joy_hat(0)
            _hx_p = getattr(self, '_menu_hat_x_prev', 0)
            _hy_p = getattr(self, '_menu_hat_y_prev', 0)
            self._menu_hat_x_prev = _hx
            self._menu_hat_y_prev = _hy

            self._vjoy_up    = (_hy ==  1) and (_hy_p != 1)
            self._vjoy_dn    = (_hy == -1) and (_hy_p != -1)
            self._vjoy_left  = (_hx == -1) and (_hx_p != -1)
            self._vjoy_right = (_hx ==  1) and (_hx_p != 1)

            # SPACE: 全画面で有効
            self._vjoy_space = b5_edge
            # ESC:   レース中は無効、ポーズ中とメニューは有効
            self._vjoy_esc   = b4_edge and not is_play
            # Q/E:   レース中は無効（シフトはパドルで行う）、その他画面で有効
            self._vjoy_q     = b0_edge and not is_play
            self._vjoy_e     = b1_edge and not is_play
        else:
            self._vjoy_space = False
            self._vjoy_esc   = False
            self._vjoy_q     = False
            self._vjoy_e     = False
            self._vjoy_up = self._vjoy_dn = False
            self._vjoy_left = self._vjoy_right = False

        # ── フェード更新（フェード中は入力をブロック）──
        if self.fade_dir != 0:
            self.fade_alpha += self.fade_dir * self.fade_speed
            if self.fade_dir == 1 and self.fade_alpha >= 255:
                self.fade_alpha = 255
                if self.fade_target is not None:
                    self.state = self.fade_target
                    # ONLINE_ENTRY に遷移する時は入力モードをリセット
                    if self.state == self.STATE_ONLINE_ENTRY:
                        self.online_join_active = False
                        self.online_join_input  = ""
                    self.fade_target = None
                self.fade_dir = -1
            elif self.fade_dir == -1 and self.fade_alpha <= 0:
                self.fade_alpha = 0
                self.fade_dir = 0
            return

        if self.state == self.STATE_TITLE:
            if pyxel.btnp(pyxel.KEY_SPACE) or self._vjoy_space:
                self._start_fade(self.STATE_MENU)
                pyxel.play(1, 2)
            if (pyxel.btnp(pyxel.KEY_ESCAPE) or self._vjoy_esc):
                pyxel.quit()

        elif self.state == self.STATE_MENU:
            MENU_ITEMS = 5
            up   = pyxel.btnp(pyxel.KEY_UP) or pyxel.btnp(pyxel.KEY_W) or self._vjoy_up
            down = pyxel.btnp(pyxel.KEY_DOWN) or pyxel.btnp(pyxel.KEY_S) or self._vjoy_dn
            if up:   self.menu_focus = (self.menu_focus - 1) % MENU_ITEMS; pyxel.play(1, 1)
            if down: self.menu_focus = (self.menu_focus + 1) % MENU_ITEMS; pyxel.play(1, 1)
            if pyxel.btnp(pyxel.KEY_SPACE) or pyxel.btnp(pyxel.KEY_RETURN) or self._vjoy_space:
                pyxel.play(1, 2)
                if   self.menu_focus == 0: self._start_fade(self.STATE_MODE_SELECT)
                elif self.menu_focus == 1: self._start_fade(self.STATE_CUSTOMIZE)
                elif self.menu_focus == 2: self._start_fade(self.STATE_STATUS)
                elif self.menu_focus == 3: self.opt_focus = 0; self._start_fade(self.STATE_OPTIONS)
                elif self.menu_focus == 4: self.opt_focus = 0; self._start_fade(self.STATE_ONLINE_ENTRY)
            if (pyxel.btnp(pyxel.KEY_ESCAPE) or self._vjoy_esc): self._start_fade(self.STATE_TITLE)

        elif self.state == self.STATE_OPTIONS:
            OPT_ITEMS = 5   # TRANSMISSION, MAP DETAIL, WHEEL SENS, CONTROLS, BACK
            up   = pyxel.btnp(pyxel.KEY_UP) or pyxel.btnp(pyxel.KEY_W) or self._vjoy_up
            down = pyxel.btnp(pyxel.KEY_DOWN) or pyxel.btnp(pyxel.KEY_S) or self._vjoy_dn
            if up:   self.opt_focus = (self.opt_focus - 1) % OPT_ITEMS; pyxel.play(1, 1)
            if down: self.opt_focus = (self.opt_focus + 1) % OPT_ITEMS; pyxel.play(1, 1)
            if pyxel.btnp(pyxel.KEY_SPACE) or pyxel.btnp(pyxel.KEY_RETURN) or self._vjoy_space:
                pyxel.play(1, 1)
                if   self.opt_focus == 0: self.is_automatic = not self.is_automatic
                elif self.opt_focus == 1: pass  # MAP DETAIL は左右で操作
                elif self.opt_focus == 2: pass  # WHEEL SENS は左右で操作
                elif self.opt_focus == 3: pass  # CONTROLS はインフォ表示のみ
                elif self.opt_focus == 4: self.save_options(); self._start_fade(self.STATE_MENU)
            lr_left  = pyxel.btnp(pyxel.KEY_LEFT) or pyxel.btnp(pyxel.KEY_A) or self._vjoy_left
            lr_right = pyxel.btnp(pyxel.KEY_RIGHT) or pyxel.btnp(pyxel.KEY_D) or self._vjoy_right
            # MAP DETAIL: 左右で map_pixel_size を 1〜4 で調整
            if self.opt_focus == 1:
                if lr_left:
                    old = self.map_pixel_size
                    self.map_pixel_size = max(1, self.map_pixel_size - 1)
                    if self.map_pixel_size != old:
                        self._build_map(self.selected_course); pyxel.play(1, 1)
                if lr_right:
                    old = self.map_pixel_size
                    self.map_pixel_size = min(4, self.map_pixel_size + 1)
                    if self.map_pixel_size != old:
                        self._build_map(self.selected_course); pyxel.play(1, 1)
            # WHEEL SENS: 左右で 1〜10 で調整
            if self.opt_focus == 2:
                if lr_left:
                    self.wheel_sensitivity = max(1, self.wheel_sensitivity - 1); pyxel.play(1, 1)
                if lr_right:
                    self.wheel_sensitivity = min(10, self.wheel_sensitivity + 1); pyxel.play(1, 1)
            if (pyxel.btnp(pyxel.KEY_ESCAPE) or self._vjoy_esc):
                self.save_options()
                self._start_fade(self.STATE_MENU); pyxel.play(1, 1)

        elif self.state == self.STATE_MODE_SELECT:
            if pyxel.btnp(pyxel.KEY_LEFT) or pyxel.btnp(pyxel.KEY_A) or self._vjoy_left or \
               pyxel.btnp(pyxel.KEY_RIGHT) or pyxel.btnp(pyxel.KEY_D) or self._vjoy_right:
                self.is_time_attack = not self.is_time_attack; pyxel.play(1, 1)
            if pyxel.btnp(pyxel.KEY_SPACE) or self._vjoy_space:
                self._start_fade(self.STATE_COURSE_SELECT); pyxel.play(1, 2)
            if (pyxel.btnp(pyxel.KEY_ESCAPE) or self._vjoy_esc):
                self._start_fade(self.STATE_MENU); pyxel.play(1, 1)

        elif self.state == self.STATE_COURSE_SELECT:
            # 削除確認ダイアログ中
            if self.cs_del_confirm:
                if pyxel.btnp(pyxel.KEY_SPACE) or pyxel.btnp(pyxel.KEY_RETURN) or self._vjoy_space or pyxel.btnp(pyxel.KEY_Y):
                    self._delete_custom_course(self.selected_course)
                    self.cs_del_confirm = False; pyxel.play(1, 1)
                if pyxel.btnp(pyxel.KEY_N) or (pyxel.btnp(pyxel.KEY_ESCAPE) or self._vjoy_esc):
                    self.cs_del_confirm = False; pyxel.play(1, 1)
                return
            # コース切り替え（ランキングから best_lap_time 更新）
            if pyxel.btnp(pyxel.KEY_LEFT) or pyxel.btnp(pyxel.KEY_A) or self._vjoy_left:
                self.selected_course = (self.selected_course - 1) % len(self.COURSES)
                self._build_map(self.selected_course)
                _r = self.get_ta_ranking()
                self.best_lap_time = _r[0] if _r else self.best_times.get(self._course_key(), None)
                pyxel.play(1, 1)
            if pyxel.btnp(pyxel.KEY_RIGHT) or pyxel.btnp(pyxel.KEY_D) or self._vjoy_right:
                self.selected_course = (self.selected_course + 1) % len(self.COURSES)
                self._build_map(self.selected_course)
                _r = self.get_ta_ranking()
                self.best_lap_time = _r[0] if _r else self.best_times.get(self._course_key(), None)
                pyxel.play(1, 1)
            # ラップ数調整
            if not self.is_time_attack:
                if pyxel.btnp(pyxel.KEY_UP, 10, 2) or pyxel.btnp(pyxel.KEY_W, 10, 2) or \
                   pyxel.btnp(pyxel.KEY_RIGHT, 10, 2) or pyxel.btnp(pyxel.KEY_D, 10, 2) or self._vjoy_up:
                    self.goal_laps = min(10, self.goal_laps + 1); pyxel.play(1, 1)
                if pyxel.btnp(pyxel.KEY_DOWN, 10, 2) or pyxel.btnp(pyxel.KEY_S, 10, 2) or \
                   pyxel.btnp(pyxel.KEY_LEFT, 10, 2) or pyxel.btnp(pyxel.KEY_A, 10, 2) or self._vjoy_dn:
                    self.goal_laps = max(1, self.goal_laps - 1); pyxel.play(1, 1)
            # 決定 → 昼夜・難易度選択へ（フェード）
            if pyxel.btnp(pyxel.KEY_SPACE) or self._vjoy_space:
                self.time_sel_focus = 0; self._start_fade(self.STATE_TIME_SELECT); pyxel.play(1, 2)
            if (pyxel.btnp(pyxel.KEY_ESCAPE) or self._vjoy_esc):
                self._start_fade(self.STATE_MODE_SELECT); pyxel.play(1, 1)
            # [E] コースメーカーへ
            if pyxel.btnp(pyxel.KEY_E) or self._vjoy_e:
                self._maker_reset(); self._start_fade(self.STATE_COURSE_MAKER); pyxel.play(1, 1)
            # [DEL] 削除確認
            if (pyxel.btnp(pyxel.KEY_DELETE) or pyxel.btnp(pyxel.KEY_BACKSPACE)) \
                    and self.selected_course >= 4:
                self.cs_del_confirm = True; pyxel.play(1, 1)
            # [R] ランキング画面（タイムアタックのみ）
            if self.is_time_attack and pyxel.btnp(pyxel.KEY_R):
                self._start_fade(self.STATE_RANKING); pyxel.play(1, 2)
            # [X] コースエクスポート / [I] コースインポート
            if pyxel.btnp(pyxel.KEY_X):
                self.export_course()
            if pyxel.btnp(pyxel.KEY_I):
                self.import_course()
            # [G] ゴーストエクスポート / [L] ゴーストインポート（タイムアタックのみ）
            if self.is_time_attack and pyxel.btnp(pyxel.KEY_G):
                self.export_ghost()
            if self.is_time_attack and pyxel.btnp(pyxel.KEY_L):
                self.import_ghost()
            # 共有メッセージタイマー
            if self._share_msg_timer > 0:
                self._share_msg_timer -= 1

        elif self.state == self.STATE_TIME_SELECT:
            # フォーカス項目定義:
            #   0=DAY, 1=NIGHT
            #   2=EASY, 3=NORMAL, 4=HARD  (レース時のみ)
            #   5=RIVALS  (レース時のみ、左右で台数±1)
            #   6=START   (レース時) / 4=START (タイムアタック時)
            if self.is_time_attack:
                focus_map = {0: "day", 1: "night", 2: "ghost_on", 3: "ghost_off", 4: "start"}
            else:
                focus_map = {0: "day", 1: "night", 2: "easy", 3: "normal", 4: "hard", 5: "rivals", 6: "start"}

            up   = pyxel.btnp(pyxel.KEY_UP) or pyxel.btnp(pyxel.KEY_W) or self._vjoy_up
            down = pyxel.btnp(pyxel.KEY_DOWN) or pyxel.btnp(pyxel.KEY_S) or self._vjoy_dn
            left = pyxel.btnp(pyxel.KEY_LEFT,  10, 3) or pyxel.btnp(pyxel.KEY_A, 10, 3) or self._vjoy_left
            right= pyxel.btnp(pyxel.KEY_RIGHT, 10, 3) or pyxel.btnp(pyxel.KEY_D, 10, 3) or self._vjoy_right

            if self.is_time_attack:
                # 時間帯行(0,1) / ghost行(2,3) / START(4)
                if left or right:
                    if self.time_sel_focus in (0, 1):
                        self.time_sel_focus = 1 - self.time_sel_focus; pyxel.play(1, 1)
                    elif self.time_sel_focus in (2, 3):
                        self.time_sel_focus = 5 - self.time_sel_focus; pyxel.play(1, 1)  # 2↔3
                if up:
                    if self.time_sel_focus in (2, 3):
                        self.time_sel_focus = 0 if self.time_sel_focus == 2 else 1
                        pyxel.play(1, 1)
                    elif self.time_sel_focus == 4:
                        self.time_sel_focus = 2; pyxel.play(1, 1)
                if down:
                    if self.time_sel_focus in (0, 1):
                        self.time_sel_focus = 2 if self.time_sel_focus == 0 else 3
                        pyxel.play(1, 1)
                    elif self.time_sel_focus in (2, 3):
                        self.time_sel_focus = 4; pyxel.play(1, 1)
            else:
                # 時間帯行(0,1) / 難易度行(2,3,4) / rivals行(5) / START(6)
                if left:
                    if self.time_sel_focus == 1:   self.time_sel_focus = 0; pyxel.play(1, 1)
                    elif self.time_sel_focus == 3: self.time_sel_focus = 2; pyxel.play(1, 1)
                    elif self.time_sel_focus == 4: self.time_sel_focus = 3; pyxel.play(1, 1)
                    elif self.time_sel_focus == 5:
                        self.num_rivals = max(1, self.num_rivals - 1); pyxel.play(1, 1)
                if right:
                    if self.time_sel_focus == 0:   self.time_sel_focus = 1; pyxel.play(1, 1)
                    elif self.time_sel_focus == 2: self.time_sel_focus = 3; pyxel.play(1, 1)
                    elif self.time_sel_focus == 3: self.time_sel_focus = 4; pyxel.play(1, 1)
                    elif self.time_sel_focus == 5:
                        self.num_rivals = min(11, self.num_rivals + 1); pyxel.play(1, 1)
                if up:
                    if self.time_sel_focus in (0, 1):
                        pass
                    elif self.time_sel_focus in (2, 3, 4):
                        self.time_sel_focus = 0 if self.time_sel_focus == 2 else 1
                        pyxel.play(1, 1)
                    elif self.time_sel_focus == 5:
                        self.time_sel_focus = 2; pyxel.play(1, 1)
                    elif self.time_sel_focus == 6:
                        self.time_sel_focus = 5; pyxel.play(1, 1)
                if down:
                    if self.time_sel_focus in (0, 1):
                        self.time_sel_focus = 2 if self.time_sel_focus == 0 else 4
                        pyxel.play(1, 1)
                    elif self.time_sel_focus in (2, 3, 4):
                        self.time_sel_focus = 5; pyxel.play(1, 1)
                    elif self.time_sel_focus == 5:
                        self.time_sel_focus = 6; pyxel.play(1, 1)

            # SPACEで選択実行
            if pyxel.btnp(pyxel.KEY_SPACE) or pyxel.btnp(pyxel.KEY_RETURN) or self._vjoy_space:
                kind = focus_map.get(self.time_sel_focus, "")
                if kind == "day":
                    self.is_night_mode = False; pyxel.play(1, 1)
                elif kind == "night":
                    self.is_night_mode = True; pyxel.play(1, 1)
                elif kind == "ghost_on":
                    self.ghost_enabled = True; pyxel.play(1, 1)
                elif kind == "ghost_off":
                    self.ghost_enabled = False; pyxel.play(1, 1)
                elif kind == "easy":
                    self.difficulty = 0; pyxel.play(1, 1)
                elif kind == "normal":
                    self.difficulty = 1; pyxel.play(1, 1)
                elif kind == "hard":
                    self.difficulty = 2; pyxel.play(1, 1)
                elif kind == "rivals":
                    pass  # 左右キーで操作するため SPACE は無視
                elif kind == "start":
                    self.reset(); self._start_fade(self.STATE_PLAY); pyxel.play(1, 2)

            if (pyxel.btnp(pyxel.KEY_ESCAPE) or self._vjoy_esc):
                self._start_fade(self.STATE_COURSE_SELECT); pyxel.play(1, 1)

        elif self.state == self.STATE_COURSE_MAKER:
            self._maker_update()

        elif self.state == self.STATE_STATUS:
            if (pyxel.btnp(pyxel.KEY_ESCAPE) or self._vjoy_esc): self._start_fade(self.STATE_MENU); pyxel.play(1, 1)

        elif self.state == self.STATE_RANKING:
            if (pyxel.btnp(pyxel.KEY_ESCAPE) or self._vjoy_esc): self._start_fade(self.STATE_COURSE_SELECT); pyxel.play(1, 1)
        elif self.state == self.STATE_ONLINE_ENTRY:
            # ── エントリー画面: CREATE / JOIN 選択 ──
            import string as _str

            if self.online_join_active:
                # ── テキスト入力モード: ESC以外はすべてテキストボックスへ ──
                if pyxel.btnp(pyxel.KEY_ESCAPE) or self._vjoy_esc:
                    # ESCでテキスト入力モードを閉じる（メニューには戻らない）
                    self.online_join_active = False
                    self.online_join_input  = ""
                    pyxel.play(1, 1)
                else:
                    # バックスペース
                    if pyxel.btnp(pyxel.KEY_BACKSPACE) and self.online_join_input:
                        self.online_join_input = self.online_join_input[:-1]; pyxel.play(1, 1)
                    # ENTERで確定（ルームID入力済みの場合のみ接続）
                    elif pyxel.btnp(pyxel.KEY_RETURN):
                        if self.online_join_input:
                            chars = _str.ascii_lowercase + _str.digits
                            self.online_my_id    = "p_" + "".join(random.choices(chars, k=4))
                            self.online_room_id  = self.online_join_input.strip()  # 前後スペース除去
                            self.online_is_host  = False
                            self.online_grid_idx = -1
                            self.online_peers    = {}
                            self._peer_interp    = {}
                            self._sent_join      = False
                            self._last_join_broadcast_t = 0
                            self.online_join_active = False
                            self.online_client   = OnlineClient(
                                "", self.online_room_id, self.online_my_id)
                            self.online_status   = "Connecting..."
                            print(f"[JOIN] room_id={repr(self.online_room_id)}")
                            self._start_fade(self.STATE_ONLINE_LOBBY); pyxel.play(1, 2)
                    else:
                        # WASD含むすべてのキー入力をテキストボックスへ
                        for key, ch in [
                            (pyxel.KEY_A,'a'),(pyxel.KEY_B,'b'),(pyxel.KEY_C,'c'),(pyxel.KEY_D,'d'),
                            (pyxel.KEY_E,'e'),(pyxel.KEY_F,'f'),(pyxel.KEY_G,'g'),(pyxel.KEY_H,'h'),
                            (pyxel.KEY_I,'i'),(pyxel.KEY_J,'j'),(pyxel.KEY_K,'k'),(pyxel.KEY_L,'l'),
                            (pyxel.KEY_M,'m'),(pyxel.KEY_N,'n'),(pyxel.KEY_O,'o'),(pyxel.KEY_P,'p'),
                            (pyxel.KEY_Q,'q'),(pyxel.KEY_R,'r'),(pyxel.KEY_S,'s'),(pyxel.KEY_T,'t'),
                            (pyxel.KEY_U,'u'),(pyxel.KEY_V,'v'),(pyxel.KEY_W,'w'),(pyxel.KEY_X,'x'),
                            (pyxel.KEY_Y,'y'),(pyxel.KEY_Z,'z'),
                            (pyxel.KEY_0,'0'),(pyxel.KEY_1,'1'),(pyxel.KEY_2,'2'),(pyxel.KEY_3,'3'),
                            (pyxel.KEY_4,'4'),(pyxel.KEY_5,'5'),(pyxel.KEY_6,'6'),(pyxel.KEY_7,'7'),
                            (pyxel.KEY_8,'8'),(pyxel.KEY_9,'9'),(pyxel.KEY_MINUS,'-'),
                            (pyxel.KEY_UNDERSCORE,'_'),
                        ]:
                            if pyxel.btnp(key) and len(self.online_join_input) < 20:
                                self.online_join_input += ch; pyxel.play(1, 1)
            else:
                # ── 通常モード: CREATE / JOIN ボタン選択 ──
                if pyxel.btnp(pyxel.KEY_LEFT) or pyxel.btnp(pyxel.KEY_A) or self._vjoy_left:
                    self.online_entry_mode = 0; pyxel.play(1, 1)
                if pyxel.btnp(pyxel.KEY_RIGHT) or pyxel.btnp(pyxel.KEY_D) or self._vjoy_right:
                    self.online_entry_mode = 1; pyxel.play(1, 1)

                if pyxel.btnp(pyxel.KEY_RETURN) or pyxel.btnp(pyxel.KEY_SPACE) or self._vjoy_space:
                    if self.online_entry_mode == 1:
                        # JOIN: ENTER/SPACEでテキスト入力モードへ移行
                        self.online_join_active = True
                        self.online_join_input  = ""
                        pyxel.play(1, 1)
                    else:
                        # CREATE: ENTER/SPACEで即ルームを作成
                        chars = _str.ascii_lowercase + _str.digits
                        self.online_my_id    = "p_" + "".join(random.choices(chars, k=4))
                        self.online_room_id  = "room-" + "".join(random.choices(chars, k=6))
                        self.online_is_host  = True
                        self.online_grid_idx = 0
                        self.online_peers    = {}
                        self._peer_interp    = {}
                        self._sent_join      = False
                        self._last_join_broadcast_t = 0
                        self.online_client   = OnlineClient(
                            "", self.online_room_id, self.online_my_id)
                        self.online_status   = "Connecting..."
                        self._start_fade(self.STATE_ONLINE_LOBBY); pyxel.play(1, 2)

                if (pyxel.btnp(pyxel.KEY_ESCAPE) or self._vjoy_esc):
                    self.online_join_input  = ""
                    self.online_join_active = False
                    self._start_fade(self.STATE_MENU); pyxel.play(1, 1)

        elif self.state == self.STATE_ONLINE_LOBBY:
            # ── 共通: メッセージ受信処理 ──
            if self.online_client:
                for msg in self.online_client.recv_all():
                    mtype = msg.get("type", "pos")
                    pid   = msg.get("player_id", "")
                    print(f"[LOBBY recv] type={mtype} pid={pid}")  # デバッグ

                    if mtype == "pos" and pid and pid != self.online_my_id:
                        # 位置データはPLAY中だけ処理
                        pass

                    elif mtype == "join" and pid and pid != self.online_my_id:
                        if pid not in self.online_peers:
                            self.online_peers[pid] = {"x": 0, "y": 0,
                                                      "angle": 0, "vel": 0}
                            print(f"[LOBBY] peer追加: {pid}, 合計: {len(self.online_peers)+1}人")
                        # join受信したら自分もjoinを返す（相互認識）
                        self.online_client.send_priority({
                            "type": "join",
                            "player_id": self.online_my_id,
                        })

                    elif mtype == "leave" and pid:
                        self.online_peers.pop(pid, None)

                    elif mtype == "settings":
                        # ホストが送ってきたコース・設定情報
                        self.online_host_settings = msg

                    elif mtype == "start":
                        # ホストがスタートを押した
                        self.online_lobby_ready = True
                        # ゲストはホストの設定を反映してレース開始
                        if not self.online_is_host:
                            # startメッセージ自体にもコース情報が入っている（settings未着時の救済）
                            s = msg if msg.get("course_idx") is not None else self.online_host_settings
                            if s:
                                cidx = s.get("course_idx", 0)
                                if 0 <= cidx < len(self.COURSES):
                                    self.selected_course = cidx
                                    self._build_map(cidx)
                                self.is_night_mode = s.get("night", False)
                                self.goal_laps     = s.get("laps", 3)
                            # settings未着でもレースは必ず開始する
                            self.reset()
                            self._start_fade(self.STATE_PLAY); pyxel.play(1, 2)

                # 接続完了したら join を定期送信（2秒ごと）して確実に届ける
                # 一度きりの _sent_join では送信失敗時にリカバリできないため
                if self.online_client.connected:
                    now_t = _time.monotonic()
                    if now_t - getattr(self, '_last_join_broadcast_t', 0) > 2.0:
                        self._last_join_broadcast_t = now_t
                        self.online_client.send_priority({
                            "type": "join",
                            "player_id": self.online_my_id,
                        })
                        print(f"[LOBBY] join送信: {self.online_my_id} → channel={self.online_client._channel}")

                # ステータス表示文字列を更新
                if self.online_client.connected:
                    np = len(self.online_peers)
                    self.online_status = (f"Room: {self.online_room_id}  "
                                          f"Players: {np + 1}/4")
                elif self.online_client.error:
                    self.online_status = f"Error: {self.online_client.error}"
                else:
                    self.online_status = "Connecting..."

            # ── ホスト専用: コース選択・スタート操作 ──
            if self.online_is_host and self.online_client and self.online_client.connected:
                # A/D でコース変更
                if pyxel.btnp(pyxel.KEY_LEFT) or pyxel.btnp(pyxel.KEY_A) or self._vjoy_left:
                    self.selected_course = (self.selected_course - 1) % 4
                    self._build_map(self.selected_course); pyxel.play(1, 1)
                    self._online_broadcast_settings()
                if pyxel.btnp(pyxel.KEY_RIGHT) or pyxel.btnp(pyxel.KEY_D) or self._vjoy_right:
                    self.selected_course = (self.selected_course + 1) % 4
                    self._build_map(self.selected_course); pyxel.play(1, 1)
                    self._online_broadcast_settings()
                # W/S でラップ数変更
                if pyxel.btnp(pyxel.KEY_UP) or pyxel.btnp(pyxel.KEY_W) or self._vjoy_up:
                    self.goal_laps = min(10, self.goal_laps + 1); pyxel.play(1, 1)
                    self._online_broadcast_settings()
                if pyxel.btnp(pyxel.KEY_DOWN) or pyxel.btnp(pyxel.KEY_S) or self._vjoy_dn:
                    self.goal_laps = max(1, self.goal_laps - 1); pyxel.play(1, 1)
                    self._online_broadcast_settings()
                # N で昼夜切り替え
                if pyxel.btnp(pyxel.KEY_N):
                    self.is_night_mode = not self.is_night_mode; pyxel.play(1, 1)
                    self._online_broadcast_settings()
                # SPACE/ENTER でレース開始
                if pyxel.btnp(pyxel.KEY_SPACE) or pyxel.btnp(pyxel.KEY_RETURN) or self._vjoy_space:
                    # settings と start を確実に順番送信
                    self._online_broadcast_settings()
                    _time.sleep(0.06)   # settingsが先に届くよう少し待つ
                    self.online_client.send_priority({
                        "type": "start",
                        "player_id": self.online_my_id,
                        # startにもコース情報を埋め込む（settings未着のゲスト救済）
                        "course_idx":  self.selected_course,
                        "night":       self.is_night_mode,
                        "laps":        self.goal_laps,
                        "course_name": self.COURSES[self.selected_course]["name"],
                    })
                    self.reset()
                    self._start_fade(self.STATE_PLAY); pyxel.play(1, 2)

            if (pyxel.btnp(pyxel.KEY_ESCAPE) or self._vjoy_esc):
                if self.online_client:
                    self.online_client.send({"type": "leave",
                                             "player_id": self.online_my_id})
                self.online_client     = None
                self.online_peers      = {}
                self._peer_interp      = {}
                self.online_room_id    = ""
                self._sent_join        = False
                self.online_lobby_ready = False
                self._start_fade(self.STATE_ONLINE_ENTRY); pyxel.play(1, 1)
        elif self.state == self.STATE_PAUSE:
            if self.pause_quit_confirm:
                if pyxel.btnp(pyxel.KEY_SPACE) or pyxel.btnp(pyxel.KEY_RETURN) or self._vjoy_space or pyxel.btnp(pyxel.KEY_Y):
                            self.pause_quit_confirm = False; self.reset(); self._start_fade(self.STATE_MENU)
                if pyxel.btnp(pyxel.KEY_N) or (pyxel.btnp(pyxel.KEY_ESCAPE) or self._vjoy_esc):
                    self.pause_quit_confirm = False; pyxel.play(1, 1)
            else:
                up   = pyxel.btnp(pyxel.KEY_UP) or pyxel.btnp(pyxel.KEY_W) or self._vjoy_up
                down = pyxel.btnp(pyxel.KEY_DOWN) or pyxel.btnp(pyxel.KEY_S) or self._vjoy_dn
                if up:   self.pause_focus = (self.pause_focus - 1) % 3; pyxel.play(1, 1)
                if down: self.pause_focus = (self.pause_focus + 1) % 3; pyxel.play(1, 1)
                if pyxel.btnp(pyxel.KEY_SPACE) or pyxel.btnp(pyxel.KEY_RETURN) or self._vjoy_space:
                    if   self.pause_focus == 0: self._start_fade(self.STATE_PLAY); pyxel.play(1, 1)
                    elif self.pause_focus == 1: self.reset(); self._start_fade(self.STATE_PLAY); pyxel.play(1, 2)
                    elif self.pause_focus == 2: self.pause_quit_confirm = True; pyxel.play(1, 1)
                if (pyxel.btnp(pyxel.KEY_ESCAPE) or self._vjoy_esc): self._start_fade(self.STATE_PLAY); pyxel.play(1, 1)

        elif self.state == self.STATE_CUSTOMIZE:
            # タブ切り替え: Q/E のみ（WASD はカラータブで色選択に使う）
            if pyxel.btnp(pyxel.KEY_Q) or self._vjoy_q:
                self.cust_tab = (self.cust_tab - 1) % 4
                pyxel.play(1, 1)
            if pyxel.btnp(pyxel.KEY_E) or self._vjoy_e:
                self.cust_tab = (self.cust_tab + 1) % 4
                pyxel.play(1, 1)

            if self.cust_tab == 0:
                # ── カラー選択: WASD で2Dグリッド移動 ──
                n            = len(self.CAR_COLORS)
                cols_per_row = 4
                rows         = (n + cols_per_row - 1) // cols_per_row
                cur_row      = self.cust_color_sel // cols_per_row
                cur_col      = self.cust_color_sel % cols_per_row

                if pyxel.btnp(pyxel.KEY_UP) or pyxel.btnp(pyxel.KEY_W) or self._vjoy_up:
                    new_row = (cur_row - 1) % rows
                    new_idx = new_row * cols_per_row + cur_col
                    self.cust_color_sel = min(new_idx, n - 1)
                    pyxel.play(1, 1)
                if pyxel.btnp(pyxel.KEY_DOWN) or pyxel.btnp(pyxel.KEY_S) or self._vjoy_dn:
                    new_row = (cur_row + 1) % rows
                    new_idx = new_row * cols_per_row + cur_col
                    self.cust_color_sel = min(new_idx, n - 1)
                    pyxel.play(1, 1)
                if pyxel.btnp(pyxel.KEY_LEFT) or pyxel.btnp(pyxel.KEY_A) or self._vjoy_left:
                    new_col = (cur_col - 1) % cols_per_row
                    new_idx = cur_row * cols_per_row + new_col
                    if new_idx < n:
                        self.cust_color_sel = new_idx
                    pyxel.play(1, 1)
                if pyxel.btnp(pyxel.KEY_RIGHT) or pyxel.btnp(pyxel.KEY_D) or self._vjoy_right:
                    new_col = (cur_col + 1) % cols_per_row
                    new_idx = cur_row * cols_per_row + new_col
                    if new_idx < n:
                        self.cust_color_sel = new_idx
                    pyxel.play(1, 1)
                if pyxel.btnp(pyxel.KEY_SPACE) or pyxel.btnp(pyxel.KEY_RETURN) or self._vjoy_space:
                    sel = self.cust_color_sel
                    owned = self.car_data.get("owned_colors", [0])
                    if sel in owned:
                        # 購入済み → 装備
                        self.car_color = self.CAR_COLORS[sel]["col"]
                        self.car_data["color_idx"] = sel
                        self.save_car_data()
                        self.cust_msg = "COLOR EQUIPPED!"
                        self.cust_msg_timer = 90
                        pyxel.play(1, 2)
                    else:
                        price = self.CAR_COLORS[sel]["price"]
                        if self.credits >= price:
                            self.credits -= price
                            self.save_credits()
                            owned.append(sel)
                            self.car_data["owned_colors"] = owned
                            self.car_color = self.CAR_COLORS[sel]["col"]
                            self.car_data["color_idx"] = sel
                            self.save_car_data()
                            self.cust_msg = f"BOUGHT & EQUIPPED! -{price}CR"
                            self.cust_msg_timer = 90
                            pyxel.play(1, 2)
                        else:
                            self.cust_msg = "NOT ENOUGH CREDITS!"
                            self.cust_msg_timer = 90
                            pyxel.play(1, 1)

            else:
                # ── アップグレード（エンジン/ブレーキ/軽量化）──
                key_map = {1: "engine_lv", 2: "brake_lv", 3: "weight_lv"}
                lv_key  = key_map[self.cust_tab]
                cost_mult = 2000 if self.cust_tab == 3 else 1000

                if pyxel.btnp(pyxel.KEY_SPACE) or pyxel.btnp(pyxel.KEY_RETURN) or self._vjoy_space or pyxel.btnp(pyxel.KEY_UP) or pyxel.btnp(pyxel.KEY_W) or self._vjoy_up:
                    cur_lv = self.car_data[lv_key]
                    if cur_lv >= 10:
                        self.cust_msg = "MAX LEVEL!"
                        self.cust_msg_timer = 90
                    else:
                        next_lv  = cur_lv + 1
                        cost     = next_lv * cost_mult
                        if self.credits >= cost:
                            self.credits -= cost
                            self.save_credits()
                            self.car_data[lv_key] = next_lv
                            self.save_car_data()
                            self.cust_msg = f"UPGRADED TO LV{next_lv}! -{cost}CR"
                            self.cust_msg_timer = 120
                            pyxel.play(1, 2)
                        else:
                            self.cust_msg = f"NEED {next_lv * cost_mult}CR!"
                            self.cust_msg_timer = 90
                            pyxel.play(1, 1)

            if self.cust_msg_timer > 0:
                self.cust_msg_timer -= 1

            if (pyxel.btnp(pyxel.KEY_ESCAPE) or self._vjoy_esc):
                self._start_fade(self.STATE_MENU); pyxel.play(1, 1)

        elif self.state == self.STATE_PLAY:
            # 性能乗数をフレーム先頭で1回だけ計算してキャッシュ
            self._perf_cache = self.get_perf_mult()
            if self.online_client and self.online_client.connected:
                self.online_client.send({
                    "type":      "pos",
                    "player_id": self.online_my_id,
                    "x":         self.car_world_x,
                    "y":         self.car_world_y,
                    "angle":     self.car_angle,
                    "vel":       self.velocity,
                    "vx":        getattr(self, 'vx', 0.0),
                    "vy":        getattr(self, 'vy', 0.0),
                    "lap":       getattr(self, "current_lap", 1),
                    "progress":  getattr(self, "car_progress", 0),
                    "is_goal":   bool(getattr(self, "is_goal", False)),
                })
                for msg in self.online_client.recv_all():
                    mtype = msg.get("type", "pos")
                    pid   = msg.get("player_id", "")

                    if mtype == "pos":
                        if not pid or pid == self.online_my_id:
                            continue
                        now_t = _time.monotonic()
                        if pid not in self._peer_interp:
                            self._peer_interp[pid] = PeerInterpolator()
                            self.online_peers[pid]  = {}
                        self._peer_interp[pid].push(msg, now_t)

                    elif mtype == "goal" and pid and pid != self.online_my_id:
                        # 相手のゴールを記録
                        if not hasattr(self, 'online_finish_order'):
                            self.online_finish_order = []
                        if pid not in [e[0] for e in self.online_finish_order]:
                            self.online_finish_order.append((pid, pid[:4].upper()))

                    elif mtype == "lobby_return" and pid and pid != self.online_my_id:
                        # 相手がロビーに戻った → 自分もロビーに戻る
                        if self.is_goal:
                            pyxel.stop()
                            self.online_peers   = {}
                            self._peer_interp   = {}
                            self._sent_join     = False
                            self._last_join_broadcast_t = 0
                            self.online_finish_order = []
                            self._start_fade(self.STATE_ONLINE_LOBBY); pyxel.play(1, 2)

                # 全ピアの補間状態を毎フレーム更新（描画用）
                now_t = _time.monotonic()
                for pid, interp in self._peer_interp.items():
                    state = interp.update(now_t)
                    if state:
                        self.online_peers[pid] = state
            # 復帰中はあらゆる操作を受け付けない
            if self.is_respawning:
                self.respawn_timer += 1
                if self.respawn_timer > 60:
                    self.car_world_x = self.respawn_pos_x
                    self.car_world_y = self.respawn_pos_y
                    self.car_angle   = self.respawn_angle
                    self.velocity    = 0
                    self.vx          = 0.0
                    self.vy          = 0.0
                    self.slip_angle   = 0.0
                    self.is_sliding      = False
                    self.is_understeer   = False
                    self.is_oversteer    = False
                    self.is_traction_loss = False
                    self.is_out      = False
                    self.grass_shake = 0
                    self.out_frames  = 0
                    self.is_respawning = False
                    self.respawn_timer = 0
                return

            # ── 入力取得: キーボード + T-300 RS ハンコン ──
            # T-300 RS ボタンマッピング:
            #   Axis 0 = ステアリング (-1=左, +1=右)
            #   Axis 2 = アクセル    (-1=全開, +1=離し)
            #   Axis 3 = ブレーキ    (-1=全踏, +1=離し)
            #   Btn 4  = 左パドル → シフトダウン
            #   Btn 5  = 右パドル → シフトアップ
            #   Btn 7  = R2       → ニトロ（ブースト）
            #   Btn 9  = OPTIONS  → ESC（ポーズ）
            #   Hat 0  = 十字キー → WASD相当
            if _HAS_JOY:
                _pg.event.pump()
                joy_steer     = _joy_axis(0)
                joy_accel_raw = _joy_axis(2, deadzone=0.02)
                joy_brake_raw = _joy_axis(1, deadzone=0.02)
                joy_accel = max(0.0, (1.0 - joy_accel_raw) / 2.0)
                joy_brake = max(0.0, (1.0 - joy_brake_raw) / 2.0)
                hat_x, hat_y  = _joy_hat(0)   # 十字キー

                JOY_STEER_THRESHOLD = 0.15
                is_up    = pyxel.btn(pyxel.KEY_UP)    or pyxel.btn(pyxel.KEY_W) or (joy_accel > 0.05)
                is_down  = pyxel.btn(pyxel.KEY_DOWN)  or pyxel.btn(pyxel.KEY_S) or (joy_brake > 0.05)
                is_left  = pyxel.btn(pyxel.KEY_LEFT)  or pyxel.btn(pyxel.KEY_A) or (joy_steer < -JOY_STEER_THRESHOLD)
                is_right = pyxel.btn(pyxel.KEY_RIGHT) or pyxel.btn(pyxel.KEY_D) or (joy_steer >  JOY_STEER_THRESHOLD)

                # エッジ検出（前フレームとの差分でbtnp相当を作る）
                _pad_l   = _joy_btn(0)   # 左パドル: シフトダウン
                _pad_r   = _joy_btn(1)   # 右パドル: シフトアップ
                _r2      = _joy_btn(8)   # R2: ニトロ
                _options = _joy_btn(7)   # OPTIONS: ポーズ
                _hat_x_prev = getattr(self, '_joy_hat_x_prev', 0)
                _hat_y_prev = getattr(self, '_joy_hat_y_prev', 0)

                joy_shift_dn  = _pad_l   and not getattr(self, '_joy_pad_l_prev', False)
                joy_shift_up  = _pad_r   and not getattr(self, '_joy_pad_r_prev', False)
                joy_boost     = _r2      and not getattr(self, '_joy_r2_prev',    False)
                joy_options   = _options and not getattr(self, '_joy_opt_prev',   False)
                joy_hat_up    = (hat_y ==  1) and (_hat_y_prev != 1)
                joy_hat_dn    = (hat_y == -1) and (_hat_y_prev != -1)
                joy_hat_left  = (hat_x == -1) and (_hat_x_prev != -1)
                joy_hat_right = (hat_x ==  1) and (_hat_x_prev != 1)

                self._joy_pad_l_prev = _pad_l
                self._joy_pad_r_prev = _pad_r
                self._joy_r2_prev    = _r2
                self._joy_opt_prev   = _options
                self._joy_hat_x_prev = hat_x
                self._joy_hat_y_prev = hat_y
            else:
                joy_steer = 0.0; joy_accel = 0.0; joy_brake = 0.0
                joy_shift_dn = False; joy_shift_up  = False
                joy_boost    = False; joy_options   = False
                joy_hat_up   = False; joy_hat_dn    = False
                joy_hat_left = False; joy_hat_right = False
                is_up    = pyxel.btn(pyxel.KEY_UP)    or pyxel.btn(pyxel.KEY_W)
                is_down  = pyxel.btn(pyxel.KEY_DOWN)  or pyxel.btn(pyxel.KEY_S)
                is_left  = pyxel.btn(pyxel.KEY_LEFT)  or pyxel.btn(pyxel.KEY_A)
                is_right = pyxel.btn(pyxel.KEY_RIGHT) or pyxel.btn(pyxel.KEY_D)

            if (pyxel.btnp(pyxel.KEY_ESCAPE) or self._vjoy_esc) or joy_options:
                self.state = self.STATE_PAUSE
                pyxel.stop(0)
                return

            target_rpm = 0
            if self.start_timer > 0:
                if is_up: 
                    target_rpm = 0.9 + random.uniform(-0.05, 0.05)
            else:
                max_vel = self.GEAR_SETTINGS[self.gear]["max_vel"]
                spd_now = (self.vx**2 + self.vy**2) ** 0.5
                raw_rpm = spd_now / max_vel if max_vel > 0 else 0
                if raw_rpm > 1.0:
                    # シフトダウン時のエンジンブレーキ：vx/vy を減衰
                    eb = 1.0 - 0.008 * (raw_rpm - 1.0)
                    self.vx *= max(eb, 0.94)
                    self.vy *= max(eb, 0.94)
                target_rpm = min(raw_rpm, 1.0)

            if self.start_timer == 0:
                self.display_rpm += (target_rpm - self.display_rpm) * 0.1
            self.display_rpm += (target_rpm - self.display_rpm) * 0.2
            # display_rpm を必ず 0〜1 に収める（音ノート値オーバーフロー防止）
            self.display_rpm = max(0.0, min(self.display_rpm, 1.0))
            self.rpm = self.display_rpm

            # エンジン音再生（note は 0〜59 の範囲に厳密にクランプ）
            note = max(0, min(int(12 + self.display_rpm * 24), 59))
            pyxel.sounds[0].notes[0] = note
            pyxel.sounds[0].notes[1] = note
            pyxel.play(0, 0, loop=True)

            # オートマチックのギアチェンジ（リバース対応）
            if self.is_automatic and self.start_timer == 0 and not self.is_goal:
                spd_at = (self.vx**2 + self.vy**2) ** 0.5
                if self.is_reverse:
                    # リバース中: W（前進方向）押しで停車 → 前進ギアへ
                    if is_up and spd_at < 0.005:
                        self.is_reverse = False
                        self.reverse_wait = 0
                        self.gear = 0
                else:
                    # 前進中: S押しで停車 → 15f後(0.5秒)にリバースへ
                    if is_down and spd_at < 0.005:
                        self.reverse_wait += 1
                        if self.reverse_wait >= 15:
                            self.is_reverse = True
                            self.reverse_wait = 0
                            self.gear = 0
                    else:
                        self.reverse_wait = 0
                    # 通常オートシフト
                    if not self.is_reverse:
                        if self.auto_gear_cooldown > 0:
                            self.auto_gear_cooldown -= 1
                        else:
                            if self.rpm > 0.85 and self.gear < 4:
                                self.gear += 1
                                self.auto_gear_cooldown = 30
                            elif self.rpm < 0.4 and self.gear > 0:
                                self.gear -= 1
                                self.auto_gear_cooldown = 30

            for c in self.confetti:
                c["x"] += c["vx"]; c["y"] += c["vy"]; c["vy"] += 0.05; c["angle"] += c["va"]
            self.confetti = [c for c in self.confetti if c["y"] <= pyxel.height]

            if self.start_timer > 0:
                self.start_timer -= 1
                self.velocity = 0
                # vx/vy もゼロに固定（カウントダウン中は動かない）
                self.vx = 0.0
                self.vy = 0.0

                # start_timer 200→101: まだ赤信号、アクセルを踏むとエンスト予告
                if self.start_timer > 100 and is_up:
                    self.is_stalled = True
                elif not is_up:
                    self.is_stalled = False

                # start_timer 100→11: 赤→黄区間、アクセル保持でロケットスタート準備
                if 10 < self.start_timer <= 100 and is_up and not self.is_stalled:
                    self.is_rocket_start = True
                elif not is_up:
                    self.is_rocket_start = False

                if self.start_timer == 0:
                    if self.is_stalled:
                        self.stall_timer = 60
                        self.velocity = 0
                    elif self.is_rocket_start:
                        # vx/vy に直接初速を付与（car_angle方向へ）
                        self.velocity = 0.30
                        self.vx = math.cos(self.car_angle) * 0.30
                        self.vy = math.sin(self.car_angle) * 0.30
                        self.rocket_timer = 80
                        self.rocket_text_timer = 80

            # ロケットスタートタイマーのカウントダウン
            if self.rocket_timer > 0:
                self.rocket_timer -= 1
                # 60km/h (velocity≈0.15) を超えたら即終了
                if self.velocity > 0.15 or self.rocket_timer == 0:
                    self.rocket_timer = 0
                    self.is_rocket_start = False

            if self.is_spinning:
                self.spin_timer += 1
                spin_frames = [49, -50, 50, -50]
                self.u = spin_frames[(self.spin_timer // 2) % 4]
                self.w = 26
                if self.spin_timer > 30:
                    self.is_spinning = False
                    self.spin_timer = 0
                    pyxel.camera(0, 0)
                return

            is_offroad = (self.COURSES[self.selected_course].get("col_ground", 11) == 3)

            # ── ゴースト録画（タイムアタック・カウントダウン終了後） ──
            if self.is_time_attack and self.start_timer == 0 and not self.is_goal:
                # 毎フレーム録画
                self.ghost_record.append({
                    "x": self.car_world_x, "y": self.car_world_y,
                    "a": self.car_angle,   "u": self.u, "w": self.w
                })
                # 再生インデックス = 録画バッファ長と完全同期（途切れ防止）
                # ghost_sampleで間引かれたデータへのアクセスは描画側で処理
                self.ghost_frame_idx = len(self.ghost_record)

            if not self.is_goal and self.start_timer == 0:
                if self.is_stalled:
                    # エンスト中：速度ベクトルを急速に減衰
                    self.vx *= 0.85
                    self.vy *= 0.85
                    pyxel.play(1,4)
                    self.stall_timer -= 1
                    if self.stall_timer <= 0:
                        self.is_stalled = False
                else:
                    # ギアの手動操作はMT専用
                    if not self.is_automatic:
                        if self.is_reverse:
                            if pyxel.btnp(pyxel.KEY_E) or joy_shift_up:
                                spd_mt = (self.vx**2 + self.vy**2) ** 0.5
                                if spd_mt < 0.005:
                                    self.is_reverse = False
                                    self.gear = 0
                        else:
                            # 右パドル/Eでシフトアップ、左パドル/Qでシフトダウン
                            if pyxel.btnp(pyxel.KEY_E) or joy_shift_up:
                                self.gear = min(self.gear + 1, 4)
                            if pyxel.btnp(pyxel.KEY_Q) or joy_shift_dn:
                                spd_mt = (self.vx**2 + self.vy**2) ** 0.5
                                if self.gear == 0 and spd_mt < 0.005:
                                    self.is_reverse = True
                                else:
                                    self.gear = max(self.gear - 1, 0)
                    self.is_braking = False

                    # ブースト管理（SPACEまたはハンコンBtn23）
                    if (pyxel.btnp(pyxel.KEY_SPACE) or self._vjoy_space or joy_boost) and self.boost_cooldown == 0:
                        self.is_boosting = True
                        self.boost_timer = 30
                        self.boost_cooldown = 300

                    if self.is_boosting:
                        self.boost_timer -= 1
                        if pyxel.play_pos(2) is None and self.state != self.STATE_PAUSE:
                            pyxel.play(2, 5, loop=True)
                        if self.boost_timer <= 0:
                            pyxel.stop(2)
                            self.is_boosting = False

                    if self.boost_cooldown > 0: self.boost_cooldown -= 1

            if (pyxel.btnp(pyxel.KEY_R) or (_HAS_JOY and getattr(self, '_vjoy_space', False))) and self.is_goal:
                pyxel.stop()
                # オンライン対戦中はロビーに戻る（再戦しやすいように）
                if self.online_client and self.online_client.connected:
                    self.online_client.send_priority({
                        "type": "lobby_return",
                        "player_id": self.online_my_id,
                    })
                    # ピア情報・ゴール結果をリセットしてロビーへ
                    self.online_peers   = {}
                    self._peer_interp   = {}
                    self._sent_join     = False
                    self._last_join_broadcast_t = 0
                    self.online_finish_order = []
                    self._start_fade(self.STATE_ONLINE_LOBBY); pyxel.play(1, 2)
                else:
                    self.reset()
                    self._start_fade(self.STATE_MENU)
                return

            # 賞金アニメーション更新
            if self.is_goal and not self.is_time_attack:
                self.prize_anim_timer += 1
                if self.prize_anim_phase == 1:
                    # フェーズ1: 基本賞金を60フレームかけてカウントアップ
                    progress = min(self.prize_anim_timer / 60.0, 1.0)
                    self.prize_display = int(self.prize_amount * progress)
                    if self.prize_anim_timer >= 65:
                        self.prize_display = self.prize_amount
                        if self.prize_bonus > 0:
                            self.prize_anim_timer = 0
                            self.prize_anim_phase = 2  # ボーナスフェーズへ
                        else:
                            self.prize_anim_phase = 3
                            # クレジット加算・保存（ボーナスなし）
                            self.credits += self.prize_amount
                            self.stats["total_credits"] += self.prize_amount
                            self.save_credits()
                            self.save_stats()
                elif self.prize_anim_phase == 2:
                    # フェーズ2: ボーナスを40フレームかけてカウントアップ
                    progress = min(self.prize_anim_timer / 40.0, 1.0)
                    self.prize_display = self.prize_amount + int(self.prize_bonus * progress)
                    if self.prize_anim_timer >= 45:
                        self.prize_display = self.prize_amount + self.prize_bonus
                        self.prize_anim_phase = 3
                        # クレジット加算・保存
                        total_earned = self.prize_amount + self.prize_bonus
                        self.credits += total_earned
                        self.stats["total_credits"] += total_earned
                        self.save_credits()
                        self.save_stats()

            self.kilometer = int(self.velocity * 400) * (-1 if self.is_reverse else 1)

            # --- パーティクル生成ヘルパー ---
            # 後輪スクリーン座標（車体中央より少し下）
            rear_y      = pyxel.height - 38
            rear_cx     = pyxel.width  / 2
            tire_l_x    = rear_cx - 13   # 後輪左
            tire_r_x    = rear_cx + 13   # 後輪右

            def spawn_smoke(sx, col, vx_base=0.0, vy_base=3.0, count=1, size=2.0, life=14):
                for _ in range(count):
                    self.dirt_particles.append({
                        "x": sx + random.uniform(-3, 3),
                        "y": rear_y + random.uniform(-2, 2),
                        "vx": vx_base + random.uniform(-0.6, 0.6),
                        "vy": vy_base + random.uniform(0.5, 2.0),
                        "life": life,
                        "max_life": life,
                        "size": size + random.uniform(-0.5, 0.8),
                        "col": col,
                    })

            # ① オフロード土煙（常時）
            if is_offroad and self.velocity > 0.05 and not self.is_respawning and not self.is_out:
                if pyxel.frame_count % 2 == 0:
                    drift_vx = (self.velocity * 6) * (1 if is_left else (-1 if is_right else 0))
                    spawn_smoke(tire_l_x, 9, vx_base= drift_vx * 0.5)
                    spawn_smoke(tire_r_x, 9, vx_base=-drift_vx * 0.5)

            # ② オーバーステア時のタイヤスモーク
            # スリップ角の向きに応じて「流れる側の後輪」から出す
            # 2フレームに1回に間引いて出っぱなし感を抑える
            if not is_offroad and self.is_oversteer and self.velocity > 0.18 and not self.is_respawning:
                if pyxel.frame_count % 2 == 0:
                    slip_vx = math.sin(self.slip_angle) * self.velocity * 8
                    spawn_smoke(tire_l_x, 13, vx_base= slip_vx * 0.6, size=2.5, life=14)
                    spawn_smoke(tire_r_x, 13, vx_base=-slip_vx * 0.6, size=2.5, life=14)
                    # スリップ側のタイヤはさらに濃く
                    heavy_tire = tire_r_x if self.slip_angle > 0 else tire_l_x
                    spawn_smoke(heavy_tire, 7, vx_base=0.0, size=2.8, life=16)

            # ③ トラクション抜けのホイールスピンスモーク（後輪後方に一直線）
            # 3フレームに1回だけ生成して出っぱなしを防ぐ
            if self.is_traction_loss and self.velocity > 0.05 and not self.is_respawning:
                if pyxel.frame_count % 3 == 0:
                    spawn_smoke(tire_l_x, 13, vx_base=0.0, vy_base=4.0, size=2.0, life=10)
                    spawn_smoke(tire_r_x, 13, vx_base=0.0, vy_base=4.0, size=2.0, life=10)

            # ④ ロケットスタートスモーク
            # カウントダウン中にアクセル保持 → ホイールスピン煙
            if self.is_rocket_start and self.start_timer > 0:
                if pyxel.frame_count % 2 == 0:
                    spawn_smoke(tire_l_x, 7, vx_base=-0.5, vy_base=4.0, size=2.5, life=16)
                    spawn_smoke(tire_r_x, 7, vx_base= 0.5, vy_base=4.0, size=2.5, life=16)
            # スタート直後：rocket_timerが残っている間、大量の煙
            elif self.is_rocket_start and self.start_timer == 0 and self.rocket_timer > 0:
                burst = max(1, self.rocket_timer // 12)
                spawn_smoke(tire_l_x, 7, vx_base=-1.2, vy_base=5.5, count=burst, size=3.5, life=22)
                spawn_smoke(tire_r_x, 7, vx_base= 1.2, vy_base=5.5, count=burst, size=3.5, life=22)

            for p in self.dirt_particles:
                p["x"] += p["vx"]
                p["y"] += p["vy"]
                p["size"] += 0.3
                p["life"] -= 1
            self.dirt_particles = [p for p in self.dirt_particles if p["life"] > 0]

            # ================================================================
            # --- 慣性ベース物理モデル ---
            # vx/vy: ワールド座標の慣性速度ベクトル
            # car_angle: 車体の向き（ステアリングで操作）
            # slip_angle: 速度ベクトルと車体向きのズレ → アンダー/オーバー源
            # ================================================================

            # --- 路面グリップ係数 ---
            if is_offroad:
                grip_base   = 0.58   # オフロード：グリップ低め
                traction_limit = 0.55  # トラクション限界（低め＝空転しやすい）
            else:
                grip_base   = 0.78   # 舗装路
                traction_limit = 0.80

            # ブレーキ中はグリップ低下（ロック気味）
            if self.is_braking and self.velocity > 0.2:
                grip_base *= 0.80

            # ============================
            # ① ステアリング（車体向きを回す）
            # ============================
            if not self.is_goal:
                spd = max(self.vx**2 + self.vy**2, 0.0) ** 0.5

                # ── ハンドル慣性: steer_input を目標値に向けてじわじわ動かす ──
                steer_respond = 0.10 + 0.06 * (1.0 - min(spd / 0.6, 1.0))
                steer_return  = 0.12

                if _HAS_JOY and abs(joy_steer) > 0.04:
                    # ハンコン感度（1〜10）: ステアリング軸の入力量そのものをスケール
                    # 感度1=入力を10%に縮小（鈍感）、感度5=そのまま(×1.0)、感度10=×2.0（敏感）
                    sens = getattr(self, 'wheel_sensitivity', 5)
                    sens_scale = sens / 2.0            # 0.2〜2.0
                    scaled_steer = max(-1.0, min(1.0, joy_steer * sens_scale))
                    self.steer_input += (scaled_steer - self.steer_input) * 0.30
                elif is_left:
                    self.steer_input += (-1.0 - self.steer_input) * steer_respond
                elif is_right:
                    self.steer_input += ( 1.0 - self.steer_input) * steer_respond
                else:
                    self.steer_input += (0.0 - self.steer_input) * steer_return

                self.steer_input = max(-1.0, min(1.0, self.steer_input))

                # ── ハンドル量に応じてスプライト切り替え（|steer|>0.25 で切れ角表現）──
                if self.steer_input < -0.25:
                    self.u, self.w = -50, 26
                elif self.steer_input > 0.25:
                    self.u, self.w = 50, 26
                else:
                    self.u, self.w = 49, 0

                # ── 実際の角速度: steer_input × handling_speed ──
                if spd > 0.01:
                    steer_max = 0.052 if not is_offroad else 0.038
                    steer_max *= self._perf_cache["handling"]
                    speed_factor = (spd / 0.7) ** 1.2
                    handling_speed = steer_max / (1.0 + speed_factor * 1.3)
                    handling_speed = max(handling_speed, 0.005)
                else:
                    handling_speed = 0.0

                steer_sign = -1 if self.is_reverse else 1
                self.car_angle += self.steer_input * handling_speed * steer_sign

            # ============================
            # ② トラクション（前後力を vx/vy に加える）
            # ============================
            # 車体前方向の単位ベクトル
            fwd_x = math.cos(self.car_angle)
            fwd_y = math.sin(self.car_angle)

            # 現在の前進成分（エンジン力の基準）
            speed_along_fwd = self.vx * fwd_x + self.vy * fwd_y

            if not self.is_goal and self.start_timer == 0 and not self.is_stalled:
                if self.is_reverse:
                    # ── リバースギア（Rギア）──
                    # 最高速 40km/h ≈ velocity 0.10、加速度は1速と同じ
                    REV_MAX_VEL = 0.10
                    REV_ACCEL   = 0.002 * self.GEAR_SETTINGS[0]["accel"] * (0.8 if self.is_automatic else 1.0)
                    REV_ACCEL  *= self._perf_cache["accel"]
                    spd_r = (self.vx**2 + self.vy**2) ** 0.5
                    if is_up:
                        # W: 後退方向に加速
                        if spd_r < REV_MAX_VEL:
                            self.vx -= fwd_x * REV_ACCEL
                            self.vy -= fwd_y * REV_ACCEL
                    elif is_down:
                        # S: 減速ブレーキ
                        if spd_r > 0.001:
                            brake_r = 0.008 * self._perf_cache["brake"]
                            self.vx -= (self.vx / spd_r) * brake_r
                            self.vy -= (self.vy / spd_r) * brake_r
                    else:
                        self.vx *= 0.993
                        self.vy *= 0.993
                    self.is_traction_loss = False
                elif is_up:
                    perf = self._perf_cache
                    gear_set = self.GEAR_SETTINGS[self.gear]
                    accel_rate = 0.002 * gear_set["accel"] * (0.8 if self.is_automatic else 1.0)
                    accel_rate *= perf["accel"]
                    # ハンコンのアナログペダル強度を反映（キーボード時は常に1.0）
                    accel_depth = joy_accel if (_HAS_JOY and joy_accel > 0.05) else 1.0
                    accel_rate *= accel_depth
                    if self.is_boosting:
                        accel_rate += 0.005
                    if self.rocket_timer > 0:
                        rocket_boost = 0.006 * (self.rocket_timer / 80.0)
                        accel_rate += rocket_boost
                    if self.slipstream_active:
                        accel_rate *= 1.3

                    traction_cap = traction_limit * (0.25 + self.gear * 0.16)
                    self.is_traction_loss = (speed_along_fwd > traction_cap and self.gear <= 2)
                    if self.is_traction_loss:
                        accel_rate *= 0.30
                        rear_slip = (speed_along_fwd - traction_cap) * 0.10
                        if is_right:
                            self.vx += math.cos(self.car_angle + math.pi/2) * rear_slip
                            self.vy += math.sin(self.car_angle + math.pi/2) * rear_slip
                        else:
                            self.vx += math.cos(self.car_angle - math.pi/2) * rear_slip
                            self.vy += math.sin(self.car_angle - math.pi/2) * rear_slip

                    self.vx += fwd_x * accel_rate
                    self.vy += fwd_y * accel_rate

                elif is_down:
                    # ブレーキ：ハンコン時はペダル踏み込み量に比例
                    brake_depth = joy_brake if (_HAS_JOY and joy_brake > 0.05) else 1.0
                    brake_force = 0.008 * self._perf_cache["brake"] * brake_depth
                    spd_total = (self.vx**2 + self.vy**2) ** 0.5
                    if spd_total > 0.001:
                        self.vx -= (self.vx / spd_total) * brake_force
                        self.vy -= (self.vy / spd_total) * brake_force
                    if (is_left or is_right) and self.velocity > 0.25:
                        corner_oversteer = self.velocity * 0.012
                        if is_right:
                            self.vx += math.cos(self.car_angle + math.pi/2) * corner_oversteer
                            self.vy += math.sin(self.car_angle + math.pi/2) * corner_oversteer
                        else:
                            self.vx += math.cos(self.car_angle - math.pi/2) * corner_oversteer
                            self.vy += math.sin(self.car_angle - math.pi/2) * corner_oversteer
                    self.is_braking = True
                else:
                    # 惰性：転がり抵抗で自然減速
                    self.vx *= 0.993
                    self.vy *= 0.993
                    self.is_traction_loss = False

            elif self.is_goal:
                # ゴール後はゆっくり停止
                self.vx *= 0.982
                self.vy *= 0.982
                self.steer_input = 0.0
                self.u, self.w = 49, 0

            # ============================
            # ③ グリップ力（速度ベクトルを車体向きに引き戻す）
            # ============================
            # スリップ角：速度ベクトルと車体向きのなす角
            spd_total = (self.vx**2 + self.vy**2) ** 0.5
            grip_mult = self._perf_cache["grip"]
            if spd_total > 0.001:
                vel_angle = math.atan2(self.vy, self.vx)
                raw_slip = (vel_angle - self.car_angle + math.pi) % (2 * math.pi) - math.pi
                self.slip_angle = raw_slip

                # グリップ力のパチーノ曲線（簡易）：スリップ角が大きいほどグリップが飽和
                # アンダー弱め：飽和開始スリップ角を少し広めに
                slip_abs = abs(raw_slip)
                grip_peak_angle = 0.38   # この角度までグリップが線形増加（広めに設定）
                if slip_abs < grip_peak_angle:
                    grip_factor = grip_base * (slip_abs / grip_peak_angle)
                else:
                    # 限界超え：グリップが急低下（スライド状態）
                    over = min((slip_abs - grip_peak_angle) / 0.5, 1.0)
                    grip_factor = grip_base * (1.0 - over * 0.55)

                self.is_sliding = slip_abs > grip_peak_angle * 1.1

                # アンダー/オーバー判定
                # スリップ角の「符号」と「ステア方向」でどちらかを判別
                # raw_slip > 0 → 速度が車体より左向き（右コーナーでのアンダー or 左コーナーでのオーバー）
                turning = is_left or is_right
                if self.is_sliding and turning and self.velocity > 0.18:
                    # ステア方向とスリップ角の符号が同じ → アンダー（外に逃げる）
                    # ステア方向とスリップ角の符号が逆   → オーバー（内に巻き込む）
                    steer_sign = -1 if is_left else 1
                    slip_sign  =  1 if raw_slip > 0 else -1
                    if steer_sign == slip_sign:
                        self.is_understeer = True
                        self.is_oversteer  = False
                    else:
                        self.is_oversteer  = True
                        self.is_understeer = False
                else:
                    self.is_understeer = False
                    self.is_oversteer  = False

                # グリップ力を横方向に適用（速度ベクトルを車体向きへ引き戻す）
                # 横速度成分を計算
                side_x = math.cos(self.car_angle + math.pi/2)
                side_y = math.sin(self.car_angle + math.pi/2)
                lateral_vel = self.vx * side_x + self.vy * side_y  # 横方向速度

                correction = lateral_vel * grip_factor * grip_mult
                self.vx -= side_x * correction
                self.vy -= side_y * correction

                # 空気抵抗（高速ほど強い）
                # 係数0.00086：5速最高速(v≈0.70, 280km/h)で加速力と釣り合うよう設定
                drag = 1.0 - spd_total * 0.00086
                self.vx *= max(drag, 0.9986)
                self.vy *= max(drag, 0.9986)

                # velocityを実速度に同期（RPM・スピードメーター用）
                self.velocity = spd_total
            else:
                self.slip_angle    = 0.0
                self.is_sliding    = False
                self.is_understeer    = False
                self.is_oversteer     = False
                self.is_traction_loss = False
                self.velocity         = 0.0

            # ============================
            # ④ 位置を更新
            # ============================
            self.car_world_x += self.vx
            self.car_world_y += self.vy

            # 走行距離・時間を積算（カウントダウン後・ゴール前のみ）
            if self.start_timer == 0 and not self.is_goal:
                self.session_distance += (self.vx**2 + self.vy**2) ** 0.5
                self.session_frames   += 1

            # ====================================================
            # ライバルの更新と、当たり判定（押し出し処理）
            # ====================================================
            can_move = (self.start_timer <= 0) # カウントダウンが終わったらTrue

            # プレイヤー性能乗数をライバルにも反映（平均値で調整）
            perf = self._perf_cache
            # 難易度補正: 初級0.6, 中級0.8, 上級1.0
            diff_mult = [0.6, 0.8, 1.0][self.difficulty]
            rival_speed_base = max(diff_mult, (perf["accel"] + perf["max_vel"]) / 2.0 * diff_mult)
            for rival in self.rivals:
               rival.update(
                   self.smooth_points, self.GEAR_SETTINGS, is_offroad, can_move,
                   self.car_progress, self.racing_line,
                   rival_speed_base * rival.perf_scale,
                   map_image=pyxel.image(1),
                   ground_col=self.COURSES[self.selected_course]["col_ground"],
                   other_rivals=self.rivals,
               )
            
            # ====================================================
            # 車体サイズ（スプライト49x24px を投影式から逆算）
            # 幅(半): 0.41、長(半): 0.20 が実寸だが
            # 最高速 0.70/frame に対し前後 0.40 はトンネリングが起きるため
            # 前後は 0.35 に拡張してトンネリングを防ぐ
            CAR_HW = 0.50   # 半幅（横）
            CAR_HL = 0.52   # 半長（前後）

            def obb_test(ax, ay, a_ang, bx, by, b_ang):
                """
                2つのOBB（向き付き矩形）の分離軸テスト。
                衝突していれば (押し出し法線nx,ny, めり込み量ov) を返す。
                していなければ None。
                A・B 両方の軸で最小めり込み軸を選ぶ。
                """
                dx = bx - ax
                dy = by - ay

                # A・B それぞれの前方/横方向の単位ベクトル
                axes = [
                    ( math.cos(a_ang),  math.sin(a_ang), CAR_HL),  # A前後軸
                    (-math.sin(a_ang),  math.cos(a_ang), CAR_HW),  # A横軸
                    ( math.cos(b_ang),  math.sin(b_ang), CAR_HL),  # B前後軸
                    (-math.sin(b_ang),  math.cos(b_ang), CAR_HW),  # B横軸
                ]

                min_ov = float('inf')
                best_nx = best_ny = 0.0

                for ax2, ay2, half_a in axes:
                    # AとBをこの軸に投影した範囲の合計半径
                    # B の投影半径 = |B前後 dot axis|*HL + |B横 dot axis|*HW
                    proj_b = (abs(math.cos(b_ang)*ax2 + math.sin(b_ang)*ay2) * CAR_HL +
                              abs(-math.sin(b_ang)*ax2 + math.cos(b_ang)*ay2) * CAR_HW)
                    total  = half_a + proj_b
                    # 中心間距離をこの軸に投影
                    center_proj = dx * ax2 + dy * ay2
                    overlap = total - abs(center_proj)
                    if overlap <= 0:
                        return None          # この軸で分離 → 衝突なし
                    if overlap < min_ov:
                        min_ov = overlap
                        sign   = 1.0 if center_proj > 0 else -1.0
                        best_nx = ax2 * sign
                        best_ny = ay2 * sign

                return best_nx, best_ny, min_ov

            def spawn_sparks_world(wx, wy, impact=0.02):
                """衝突点(ワールド座標)にスパーク生成。impactが大きいほど多く・速く飛ぶ。"""
                horizon = 80; cam_z = 40.0; fov = 1.3; sf = 0.02
                dx = wx - self.car_world_x
                dy = wy - self.car_world_y
                sn = math.sin(self.car_angle); cs = math.cos(self.car_angle)
                lz =  dx * cs + dy * sn
                lx = -dx * sn + dy * cs
                if lz < 0.1:
                    return   # カメラ後方は描画しない
                dy_s = (cam_z * 100.0 * sf) / lz
                sx = pyxel.width / 2 + (lx * 100.0) / (fov * lz)
                sy = horizon + dy_s
                # 衝突強度に応じてパーティクル数を変える（最低15、最大40）
                count = min(40, max(15, int(impact * 800)))
                for _ in range(count):
                    spd_s   = random.uniform(1.5, 5.0) * (1.0 + impact * 8)
                    ang_s   = random.uniform(0, math.pi * 2)
                    stretch = random.uniform(1.5, 4.0)   # 尾引き長さ
                    self.spark_particles.append({
                        "x":  sx + random.uniform(-3, 3),
                        "y":  sy + random.uniform(-3, 3),
                        "vx": math.cos(ang_s) * spd_s,
                        "vy": math.sin(ang_s) * spd_s - random.uniform(0.5, 2.0),
                        "stretch": stretch,
                        "life":    random.randint(8, 20),
                        "max_life": 20,
                        "col": random.choice([10, 10, 9, 9, 8, 7, 7]),  # 黄金〜白
                        "size": random.uniform(1.0, 2.5),
                    })

            def apply_impulse(avx, avy, bvx, bvy, nx, ny, rest=0.55):
                rel_vn = (avx - bvx) * nx + (avy - bvy) * ny
                return rel_vn * rest if rel_vn < 0 else 0.0

            # ① ライバル同士の当たり判定
            for i in range(len(self.rivals)):
                for j in range(i + 1, len(self.rivals)):
                    r1 = self.rivals[i]
                    r2 = self.rivals[j]
                    hit = obb_test(r1.x, r1.y, r1.angle, r2.x, r2.y, r2.angle)
                    if hit:
                        nx, ny, ov = hit
                        r1.x -= nx * ov * 0.5; r1.y -= ny * ov * 0.5
                        r2.x += nx * ov * 0.5; r2.y += ny * ov * 0.5
                        imp = apply_impulse(r1.vx, r1.vy, r2.vx, r2.vy, nx, ny)
                        r1.vx -= nx * imp; r1.vy -= ny * imp
                        r2.vx += nx * imp; r2.vy += ny * imp

            # ② 自車とライバルの当たり判定
            for r in self.rivals:
                hit = obb_test(self.car_world_x, self.car_world_y, self.car_angle,
                               r.x, r.y, r.angle)
                if hit:
                    nx, ny, ov = hit
                    self.car_world_x -= nx * ov * 0.5
                    self.car_world_y -= ny * ov * 0.5
                    r.x += nx * ov * 0.5; r.y += ny * ov * 0.5
                    imp = apply_impulse(self.vx, self.vy, r.vx, r.vy, nx, ny)
                    self.vx -= nx * imp;  self.vy -= ny * imp
                    r.vx   += nx * imp;   r.vy   += ny * imp
                    if abs(imp) > 0.002:
                        self.shake_amount = min(abs(imp) * 60, 4.0)
                        self.collision_count += 1
            # ====================================================

            # ── スリップストリーム判定 ──
            # 条件：他車のすぐ真後ろ 1.2〜2.8ワールド単位・横ズレ1以内
            SLIP_NEAR = 1.2
            SLIP_FAR  = 2.8
            SLIP_SIDE = 1.0
            SLIP_FRAMES = 45  # 1.5秒 (30fps) ← 旧15の3倍
            in_slip_zone = False
            fwd_cx = math.cos(self.car_angle)
            fwd_cy = math.sin(self.car_angle)
            for r in self.rivals:
                dx_s = r.x - self.car_world_x
                dy_s = r.y - self.car_world_y
                fwd_dot  = dx_s * fwd_cx + dy_s * fwd_cy
                side_dot = abs(-dx_s * fwd_cy + dy_s * fwd_cx)
                if SLIP_NEAR <= fwd_dot <= SLIP_FAR and side_dot < SLIP_SIDE:
                    in_slip_zone = True
                    break
            if in_slip_zone and self.velocity > 0.10 and not self.is_goal:
                self.slipstream_timer = min(self.slipstream_timer + 1, SLIP_FRAMES + 10)
            else:
                self.slipstream_timer = max(self.slipstream_timer - 1, 0)
            prev_slip = self.slipstream_active
            self.slipstream_active = (self.slipstream_timer >= SLIP_FRAMES)
            # 発動瞬間：集中線パーティクルをバースト生成
            if self.slipstream_active and not prev_slip:
                for i in range(28):
                    ang = (i / 28.0) * math.pi * 2
                    self.slipstream_particles.append({
                        "ang": ang,
                        "r_inner": random.uniform(28, 38),
                        "r_outer": random.uniform(130, 175),
                        "life": random.randint(10, 18),
                        "max_life": 18,
                        "speed": random.uniform(3.5, 5.5),
                    })
            # 発動中：数フレームおきに新しい集中線を追加
            if self.slipstream_active and pyxel.frame_count % 4 == 0:
                for i in range(random.randint(4, 8)):
                    ang = random.uniform(0, math.pi * 2)
                    self.slipstream_particles.append({
                        "ang": ang,
                        "r_inner": random.uniform(25, 40),
                        "r_outer": random.uniform(120, 165),
                        "life": random.randint(8, 14),
                        "max_life": 14,
                        "speed": random.uniform(4.0, 6.0),
                    })
            # パーティクル更新（内側から外側へ拡張）
            for wp in self.slipstream_particles[:]:
                wp["r_inner"] += wp["speed"]
                wp["r_outer"] += wp["speed"]
                wp["life"] -= 1
                if wp["life"] <= 0 or wp["r_inner"] > 200:
                    self.slipstream_particles.remove(wp)
            walls = self.COURSES[self.selected_course].get("walls", [])
            WALL_RADIUS = 0.6   # 壁との衝突半径（ワールド単位）
            for w in walls:
                wx1, wy1, wx2, wy2 = w["x1"], w["y1"], w["x2"], w["y2"]
                # 線分 (wx1,wy1)-(wx2,wy2) と点 (car_world_x, car_world_y) の最近傍
                seg_dx = wx2 - wx1; seg_dy = wy2 - wy1
                seg_len2 = seg_dx**2 + seg_dy**2
                if seg_len2 < 1e-9:
                    continue
                t_proj = ((self.car_world_x - wx1) * seg_dx +
                          (self.car_world_y - wy1) * seg_dy) / seg_len2
                t_proj = max(0.0, min(1.0, t_proj))
                closest_x = wx1 + t_proj * seg_dx
                closest_y = wy1 + t_proj * seg_dy
                diff_x = self.car_world_x - closest_x
                diff_y = self.car_world_y - closest_y
                dist = math.hypot(diff_x, diff_y)
                if dist < WALL_RADIUS and dist > 1e-6:
                    # 法線方向に押し出し + 速度反射
                    nx = diff_x / dist
                    ny = diff_y / dist
                    overlap = WALL_RADIUS - dist
                    self.car_world_x += nx * overlap
                    self.car_world_y += ny * overlap
                    # 速度の法線成分を反射（反発係数0.45）
                    vn = self.vx * nx + self.vy * ny
                    if vn < 0:
                        RESTITUTION = 0.45
                        self.vx -= (1 + RESTITUTION) * vn * nx
                        self.vy -= (1 + RESTITUTION) * vn * ny
                        # 摩擦（接線方向を減衰）
                        tx_ = -ny; ty_ = nx
                        vt = self.vx * tx_ + self.vy * ty_
                        FRICTION = 0.25
                        self.vx -= FRICTION * vt * tx_
                        self.vy -= FRICTION * vt * ty_
                        impact = abs(vn)
                        if impact > 0.005:
                            if not self.is_respawning:
                                self.shake_amount = min(impact * 50, 4.0)
                            self.collision_count += 1

            # ── プレイヤー最近傍インデックス探索（局所サーチでO(n)→O(k)）──
            SEARCH_RADIUS_P = 20
            car_closest_idx = self.car_prev_idx
            n = len(self.smooth_points)
            best_dist = float('inf')
            for offset in range(-SEARCH_RADIUS_P, SEARCH_RADIUS_P + 1):
                i = (self.car_prev_idx + offset) % n
                px, py = self.smooth_points[i]
                dist = (px - self.car_world_x) ** 2 + (py - self.car_world_y) ** 2
                if dist < best_dist:
                    best_dist = dist
                    car_closest_idx = i
                
        
            if self.car_prev_idx > n * 0.8 and car_closest_idx < n * 0.2:
                self.car_lap += 1
            elif self.car_prev_idx < n * 0.2 and car_closest_idx > n * 0.8:
                self.car_lap -= 1
            
            self.car_prev_idx = car_closest_idx
            self.car_progress = self.car_lap * n + car_closest_idx

            # --- 順位の決定（ヒステリシス付き平滑化）---
            # 進行度の生値をそのまま使うと近接時に高速切り替わりが起きるため、
            # 一定フレーム数の移動平均と変更ディレイを使ってチャタリングを防ぐ
            all_progresses = [(self.car_progress, "player")] + [(r.progress, f"rival{i}") for i, r in enumerate(self.rivals)]
            all_progresses.sort(key=lambda x: x[0], reverse=True)
            new_rank = next(i+1 for i, (_, tag) in enumerate(all_progresses) if tag == "player")
            # 順位変化にディレイを設ける（30フレーム=1秒以上同じ順位が続いたら確定）
            if not hasattr(self, '_rank_candidate'): self._rank_candidate = new_rank; self._rank_hold = 0
            if new_rank == self._rank_candidate:
                self._rank_hold += 1
                if self._rank_hold >= 30:
                    self.current_rank = self._rank_candidate
            else:
                self._rank_candidate = new_rank
                self._rank_hold = 0

            # コースアウト判定
            cu = int(self.car_world_x)
            cv = int(self.car_world_y)
            ground_col = self.COURSES[self.selected_course]["col_ground"]
            if 0 <= cu < 256 and 0 <= cv < 256:
                current_ground_col = pyxel.image(1).pget(cu, cv)
            else:
                current_ground_col = ground_col

            if current_ground_col == ground_col and not self.is_goal:
                self.is_out = True
                self.grass_shake = random.uniform(-2, 2) * self.velocity * 10
                if self.velocity > 0.15:
                    self.velocity = max(self.velocity - 0.005, 0)
                # コースアウト継続時間を計測してリスポーン発動
                self.out_frames += 1
                out_limit = self.COURSES[self.selected_course]["out_distance"]
                if self.out_frames >= out_limit:
                    prev_cp_idx = (self.next_cp_index - 1) % len(self.checkpoints)
                    cp_x, cp_y = self.checkpoints[prev_cp_idx]
                    best_dist = float("inf")
                    best_pt   = (cp_x, cp_y)
                    best_angle = self.car_angle
                    pts = self.smooth_points
                    n   = len(pts)
                    for i in range(n):
                        px, py = pts[i]
                        d = math.hypot(px - cp_x, py - cp_y)
                        if d < best_dist:
                            best_dist = d
                            nx, ny = pts[(i + 1) % n]
                            best_angle = math.atan2(ny - py, nx - px)
                            best_pt = (px, py)
                    self.respawn_pos_x = best_pt[0]
                    self.respawn_pos_y = best_pt[1]
                    self.respawn_angle = best_angle
                    self.is_respawning = True
                    self.respawn_timer = 0
                    self.out_frames    = 0
            else:
                self.is_out = False
                self.grass_shake = 0
                self.out_frames = 0

            self.update_effects()

            # --- ラップ計測・チェックポイント判定 ---
            if not self.is_goal and self.start_timer == 0:
                self.lap_frame_count += 1
                self.total_race_time = self.lap_frame_count / 30.0  # 累計レース時間(秒)

                cp_x, cp_y = self.checkpoints[self.next_cp_index]
                dist_to_cp = math.hypot(self.car_world_x - cp_x, self.car_world_y - cp_y)

                if dist_to_cp < 10.0:
                    self.next_cp_index += 1
                    if self.next_cp_index >= len(self.checkpoints):
                        lap_time = self.lap_frame_count / 30.0
                        self.last_lap_time = lap_time

                        if self.is_time_attack:
                            self.is_new_record = self.add_ta_record(lap_time)
                            # 新記録のとき録画バッファをゴーストとして保存
                            if self.is_new_record and self.ghost_record:
                                self.save_ghost(self.ghost_record)
                                frames, sample = self.load_ghost()
                                self.ghost_data   = frames
                                self.ghost_sample = sample
                            self.ghost_record    = []   # 次ラップ用にリセット
                            self.ghost_frame_idx = 0
                        else:
                            if self.best_lap_time is None or lap_time < self.best_lap_time:
                                self.best_lap_time = lap_time
                                self.is_new_record = True
                                self.best_times[self._course_key()] = lap_time
                                self.save_best_times()

                        self.current_lap += 1
                        self.lap_frame_count = 0
                        self.next_cp_index = 0

                        if not self.is_time_attack and self.current_lap > self.goal_laps:
                            self.current_lap = self.goal_laps
                            self.is_goal = True
                            pyxel.sounds[0].volumes[0] = 2
                            pyxel.play(3, 3)
                            # ゴール時の最終順位を記録
                            self.goal_rank = self.current_rank
                            # オンライン: ゴールをbroadcast
                            if self.online_client and self.online_client.connected:
                                self.online_client.send_priority({
                                    "type":      "goal",
                                    "player_id": self.online_my_id,
                                    "finish_time": getattr(self, 'total_race_time', 0),
                                })
                                # ゴール順位リストに自分を追加
                                if not hasattr(self, 'online_finish_order'):
                                    self.online_finish_order = []
                                if self.online_my_id not in [e[0] for e in self.online_finish_order]:
                                    self.online_finish_order.append((self.online_my_id, "YOU"))
                            # 賞金計算（順位賞金×周回数×難易度倍率）
                            # 台数に応じて賞金テーブルを動的生成（1位=1000固定、最下位=50）
                            total_cars = len(self.rivals) + 1
                            rank_prizes = {}
                            for rk in range(1, total_cars + 1):
                                if total_cars == 1:
                                    rank_prizes[rk] = 1000
                                else:
                                    t = (rk - 1) / (total_cars - 1)  # 0.0(1位)〜1.0(最下位)
                                    rank_prizes[rk] = int(1000 * (1 - t) + 50 * t)
                            prize_diff_mult = [0.5, 0.75, 1.0][self.difficulty]
                            base_prize = int(rank_prizes.get(self.goal_rank, 0) * self.goal_laps * prize_diff_mult)
                            clean_bonus = int(base_prize * 0.5) if self.collision_count == 0 else 0
                            self.prize_amount = base_prize
                            self.prize_bonus  = clean_bonus
                            self.prize_display = 0
                            self.prize_anim_timer = 0
                            self.prize_anim_phase = 1  # アニメーション開始
                            # 統計を更新（レース参加＋走行距離・時間）
                            self.stats["race_count"]     += 1
                            if self.goal_rank == 1:
                                self.stats["first_count"] += 1
                            self.stats["total_distance"] += self.session_distance
                            self.stats["total_frames"]   += self.session_frames
                            self.save_stats()
                            # ライバルも停止モードへ
                            for rival in self.rivals:
                                rival.is_stopping = True
                            for _ in range(100):
                                self.confetti.append({
                                    "x": random.uniform(0, pyxel.width), "y": random.uniform(-100, 0),
                                    "vx": random.uniform(-1, 1), "vy": random.uniform(1, 3),
                                    "col": random.choice([7, 8, 9, 10, 11, 12, 14, 15]),
                                    "angle": random.uniform(0, 360), "va": random.uniform(5, 15)
                                })

    def _start_fade(self, target_state):
        """指定ステートへのフェードアウト開始"""
        self.fade_target = target_state
        self.fade_dir    = 1
        self.fade_alpha  = 0

    def update_effects(self):
        for c in self.clouds:
            c["x"] += self.velocity * c["speed_factor"] * 10
            if c["x"] < -100: c["x"] = pyxel.width + 100
            if c["x"] > pyxel.width + 100: c["x"] = -100

    # ------------------------------------------------------------------
    # draw
    # ------------------------------------------------------------------

    def draw(self):
        sh_x = random.uniform(-self.shake_amount, self.shake_amount) + self.grass_shake
        sh_y = random.uniform(-self.shake_amount, self.shake_amount)

        # リスポーン中は揺れなし
        if getattr(self, 'is_respawning', False):
            sh_x = 0.0
            sh_y = 0.0

        pyxel.pal()
        pyxel.cls(0)

        if self.state == self.STATE_TITLE: self.draw_title_screen()
        elif self.state == self.STATE_MENU: self.draw_menu_screen()
        elif self.state == self.STATE_OPTIONS: self.draw_options_screen()
        elif self.state == self.STATE_STATUS: self.draw_status_screen()
        elif self.state == self.STATE_MODE_SELECT: self.draw_mode_select_screen()
        elif self.state == self.STATE_COURSE_SELECT: self.draw_course_select_screen()
        elif self.state == self.STATE_TIME_SELECT: self.draw_time_select_screen()
        elif self.state == self.STATE_RANKING: self.draw_ranking_screen()
        elif self.state == self.STATE_CUSTOMIZE: self.draw_customize_screen()
        elif self.state == self.STATE_COURSE_MAKER: self._maker_draw()
        elif self.state == self.STATE_ONLINE_LOBBY:
            self.draw_online_lobby()
        elif self.state == self.STATE_ONLINE_ENTRY:
            self.draw_online_entry()
        elif self.state == self.STATE_PLAY or self.state == self.STATE_PAUSE:
            self.draw_game_scene()
            # 順位表示（オンライン時は非表示 - オンライン順位パネルが別途ある）
            total_cars = len(self.rivals) + 1
            is_online_play = (self.online_client and self.online_client.connected)
            if not self.is_time_attack and not is_online_play:
                rank_text = f"POS: {self.current_rank} / {total_cars}"
                text_color = 10 if self.current_rank == 1 else 7
                pyxel.text(pyxel.width // 2 - 20, 10, rank_text, text_color)
            for c in self.confetti:
                self.draw_confetti(c["x"], c["y"], 3, c["col"], c["angle"])

            if self.state == self.STATE_PAUSE:
                pyxel.camera(0, 0)
            elif self.is_spinning or self.is_out: pyxel.camera(sh_x, sh_y)
            elif self.is_boosting: pyxel.camera(random.uniform(-2, 2), random.uniform(-2, 2))
            else: pyxel.camera(0, 0)

            if not self.is_goal:
                gx, gy = pyxel.width - 60, 10
                gw, gh = 50, 6
                pyxel.rectb(gx, gy, gw, gh, 7)
                if self.is_boosting:
                    fill_w = (self.boost_timer / 60) * (gw - 2)
                    pyxel.rect(gx + 1, gy + 1, fill_w, gh - 2, 9)
                    pyxel.text(gx - 25, gy, "NITRO!!", pyxel.frame_count % 16)
                else:
                    charge_pct = (150 - self.boost_cooldown) / 150
                    fill_w = charge_pct * (gw - 2)
                    col = 11 if self.boost_cooldown == 0 else 12
                    pyxel.rect(gx + 1, gy + 1, fill_w, gh - 2, col)
                    pyxel.text(gx - 25, gy, "READY", 7 if self.boost_cooldown == 0 else 5)

            if self.state == self.STATE_PAUSE: self.draw_pause_overlay()

        # リスポーン時の画面暗転（UIすべてを覆い隠す）
        if self.state in (self.STATE_PLAY, self.STATE_PAUSE) and self.is_respawning:
            pyxel.camera(0, 0)   # 揺れをリセットしてから描画
            alpha = min(self.respawn_timer / 30.0, 1.0)
            bw = int(pyxel.width * alpha)
            bh = int(pyxel.height * alpha)
            bx = (pyxel.width  - bw) // 2
            by = (pyxel.height - bh) // 2
            pyxel.rect(bx, by, bw, bh, 0)
            if self.respawn_timer > 20:
                pyxel.text(pyxel.width//2 - 30, pyxel.height//2 - 4, "RECOVERING...", 8)

        # ── 画面遷移フェードオーバーレイ ──
        if self.fade_alpha > 0:
            step = max(1, int((255 - self.fade_alpha) / 32) + 1)
            for yy in range(0, pyxel.height, step):
                pyxel.line(0, yy, pyxel.width, yy, 0)
            if self.fade_alpha >= 200:
                pyxel.rect(0, 0, pyxel.width, pyxel.height, 0)

    def draw_mode7_road(self):
        horizon = 80
        cam_z = 40.0
        fov = 1.3
        scale_factor = 0.02

        sn = math.sin(self.car_angle)
        cs = math.cos(self.car_angle)

        cd          = self.COURSES[self.selected_course]
        night_remap = cd["night_remap"]
        ground_col  = cd["col_ground"]

        # map_pixel_size (1〜4) をそのままスクリーンY/X方向のステップ幅として使う
        # 1 = 1px刻み（最精細）  4 = 4px刻み（粗い・高速）
        # 遠景（地平線に近い行）ほど1ワールドpxが小さく見えるため、
        # 遠景には設定値をそのまま適用し、近景は必ず2px以上にして
        # 足元が大きなタイル張りに見えるのを防ぐ。
        far_step  = max(1, getattr(self, 'map_pixel_size', 2))  # 遠景: 設定値そのまま
        near_step = max(2, far_step)                             # 近景: 最低2px
        # 地平線からのdy距離がこの値以下なら「遠景」扱い
        # 画面192px, horizon=80 → 残り112行。遠景は上半分=56行以内
        far_threshold = 56

        W = pyxel.width
        H = pyxel.height
        y = horizon + 1   # dy=0 は除外
        _map_img = pyxel.image(1)
        _pget = _map_img.pget

        while y < H:
            dy = y - horizon
            step = far_step if dy <= far_threshold else near_step

            z = (cam_z * 100.0) / dy
            z_map = z * scale_factor

            left_dx  = -(W / 2) * fov
            right_dx =  (W / 2) * fov

            left_dx_map  = left_dx  * (z / 100.0) * scale_factor
            right_dx_map = right_dx * (z / 100.0) * scale_factor

            map_x_left  = self.car_world_x + z_map * cs - left_dx_map  * sn
            map_y_left  = self.car_world_y + z_map * sn + left_dx_map  * cs
            map_x_right = self.car_world_x + z_map * cs - right_dx_map * sn
            map_y_right = self.car_world_y + z_map * sn + right_dx_map * cs

            steps_x = W // step
            dx_map = (map_x_right - map_x_left) / steps_x
            dy_map = (map_y_right - map_y_left) / steps_x

            current_u = map_x_left
            current_v = map_y_left

            for x in range(0, W, step):
                u = int(current_u)
                v = int(current_v)

                if 0 <= u < 256 and 0 <= v < 256:
                    col = _pget(u, v)
                else:
                    col = ground_col

                if self.is_night_mode:
                    col = night_remap.get(col, col)

                pyxel.rect(x, y, step, step, col)
                current_u += dx_map
                current_v += dy_map

            y += step

    def draw_walls_3d(self):
        """壁を3D投影で描画（上面=明るい灰, 正面=暗い灰, 縁=白ハイライト）"""
        cd = self.COURSES[self.selected_course]
        walls = cd.get("walls", [])
        if not walls:
            return

        horizon  = 80
        cam_z    = 40.0
        fov      = 1.3
        sf       = 0.02
        W        = pyxel.width
        sn = math.sin(self.car_angle)
        cs = math.cos(self.car_angle)
        WALL_H   = 3.5    # 壁の高さ（ワールド単位）

        NEAR_CLIP = 1.0   # ニアクリップ平面（壁点滅防止のため十分大きく設定）
        SCREEN_X_LIMIT = W * 4  # スクリーン外への極端な飛び出しをクランプ

        def world_to_screen(wx, wy, wz=0.0):
            """ワールド座標→スクリーン座標。前方にある場合は (sx, sy, lz) を返す"""
            dx = wx - self.car_world_x
            dy = wy - self.car_world_y
            lz =  dx * cs + dy * sn
            lx = -dx * sn + dy * cs
            if lz <= NEAR_CLIP:
                return None
            dy_s = (cam_z * 100.0 * sf) / lz
            sx   = W / 2 + (lx * 100.0) / (fov * lz)
            sy   = horizon + dy_s - wz * (cam_z * 100.0 * sf) / lz
            # スクリーン座標が極端に外れている場合はクランプ（点滅防止）
            sx = max(-SCREEN_X_LIMIT, min(SCREEN_X_LIMIT, sx))
            return sx, sy, lz

        # 夜間リマップ
        night_remap = cd.get("night_remap", {})

        def remap(col):
            if self.is_night_mode:
                return night_remap.get(col, col)
            return col

        FACE_COL   = remap(13)   # 正面（暗い灰）
        TOP_COL    = remap(5)    # 上面（やや明るい灰）
        EDGE_COL   = remap(7)    # エッジハイライト（白）
        SHADOW_COL = remap(0)    # 影（黒）

        for w in walls:
            x1, y1, x2, y2 = w["x1"], w["y1"], w["x2"], w["y2"]

            # 少なくとも1点でも前方にないとスキップ
            if world_to_screen(x1, y1) is None and world_to_screen(x2, y2) is None:
                continue

            # 片方が後方にある場合、ニアクリップして前方に押し出す
            def clip_segment(wx_a, wy_a, wx_b, wy_b):
                """線分の後方端をニアプレーン(lz=NEAR_CLIP)でクリップして返す"""
                dx_a = wx_a - self.car_world_x
                dy_a = wy_a - self.car_world_y
                lz_a = dx_a * cs + dy_a * sn
                dx_b = wx_b - self.car_world_x
                dy_b = wy_b - self.car_world_y
                lz_b = dx_b * cs + dy_b * sn
                if lz_a >= NEAR_CLIP and lz_b >= NEAR_CLIP:
                    return (wx_a, wy_a), (wx_b, wy_b)
                if lz_a < NEAR_CLIP and lz_b < NEAR_CLIP:
                    return None
                # 交点を安全に補間
                denom = lz_b - lz_a
                if abs(denom) < 1e-9:
                    return None
                t = (NEAR_CLIP - lz_a) / denom
                t = max(0.0, min(1.0, t))
                cx_ = wx_a + t * (wx_b - wx_a)
                cy_ = wy_a + t * (wy_b - wy_a)
                if lz_a < NEAR_CLIP:
                    return (cx_, cy_), (wx_b, wy_b)
                else:
                    return (wx_a, wy_a), (cx_, cy_)

            clipped = clip_segment(x1, y1, x2, y2)
            if clipped is None:
                continue
            cx1_, cy1_ = clipped[0]
            cx2_, cy2_ = clipped[1]

            b1 = world_to_screen(cx1_, cy1_, 0.0)
            b2 = world_to_screen(cx2_, cy2_, 0.0)
            t1 = world_to_screen(cx1_, cy1_, WALL_H)
            t2 = world_to_screen(cx2_, cy2_, WALL_H)

            if b1 and b2 and t1 and t2:
                bx1, by1, _ = b1
                bx2, by2, _ = b2
                tx1, ty1, _ = t1
                tx2, ty2, _ = t2

                # 正面の台形をスキャンライン塗り
                pts_face = [
                    (int(bx1), int(by1)),
                    (int(bx2), int(by2)),
                    (int(tx2), int(ty2)),
                    (int(tx1), int(ty1)),
                ]
                ys = [p[1] for p in pts_face]
                min_y = max(horizon, min(ys))
                max_y = min(pyxel.height - 1, max(ys))

                def edge_x(pa, pb, y):
                    ay, by_ = pa[1], pb[1]
                    if ay == by_:
                        return pa[0]
                    return pa[0] + (pb[0] - pa[0]) * (y - ay) / (by_ - ay)

                edges = [
                    (pts_face[0], pts_face[1]),
                    (pts_face[1], pts_face[2]),
                    (pts_face[2], pts_face[3]),
                    (pts_face[3], pts_face[0]),
                ]

                for sy_line in range(min_y, max_y + 1):
                    xs = []
                    for ea, eb in edges:
                        min_ey = min(ea[1], eb[1])
                        max_ey = max(ea[1], eb[1])
                        if min_ey <= sy_line <= max_ey:
                            xs.append(edge_x(ea, eb, sy_line))
                    if len(xs) >= 2:
                        lx_px = max(0, int(min(xs)))
                        rx_px = min(W - 1, int(max(xs)))
                        if lx_px <= rx_px:
                            pyxel.line(lx_px, sy_line, rx_px, sy_line, FACE_COL)

                # 上面（ty < by のときのみ見える）
                if ty1 < by1 or ty2 < by2:
                    lx_top = min(int(tx1), int(tx2))
                    rx_top = max(int(tx1), int(tx2))
                    y_top  = int((ty1 + ty2) / 2)
                    if horizon <= y_top < pyxel.height:
                        pyxel.line(max(0, lx_top), y_top,
                                   min(W-1, rx_top), y_top, TOP_COL)

                # エッジ（輪郭線: 立体感を出す白ライン）
                pyxel.line(int(bx1), int(by1), int(tx1), int(ty1), EDGE_COL)
                pyxel.line(int(bx2), int(by2), int(tx2), int(ty2), EDGE_COL)
                pyxel.line(int(tx1), int(ty1), int(tx2), int(ty2), EDGE_COL)
                pyxel.line(int(bx1), int(by1), int(bx2), int(by2), SHADOW_COL)

    def draw_minimap(self):
        map_x, map_y = 10, 45
        map_w, map_h = 48, 48

        pyxel.rect(map_x, map_y, map_w, map_h, 0)
        ui_col = 10 if self.is_night_mode else 7
        pyxel.rectb(map_x, map_y, map_w, map_h, ui_col)

        # キャッシュ済みコース線を使用
        for (rx1, ry1, rx2, ry2) in getattr(self, '_minimap_lines', []):
            pyxel.line(map_x + rx1, map_y + ry1, map_x + rx2, map_y + ry2, 5)

        scale = map_w / 256.0

        if not self.is_goal:
            cp_x, cp_y = self.checkpoints[self.next_cp_index]
            cp_mx = map_x + cp_x * scale
            cp_my = map_y + cp_y * scale
            cp_col = 10 if pyxel.frame_count % 10 < 5 else 9
            pyxel.circb(cp_mx, cp_my, 2, cp_col)
        for rival in self.rivals:
            rx = map_x + rival.x * scale
            ry = map_y + rival.y * scale
            pyxel.rect(rx - 1, ry - 1, 3, 3, rival.color)
        # タイムアタック: ゴーストの現在位置をミニマップに表示
        if (self.is_time_attack and self.ghost_enabled
                and self.ghost_data and self.start_timer == 0):
            sample = max(1, getattr(self, 'ghost_sample', 1))
            g_idx  = min(self.ghost_frame_idx // sample, len(self.ghost_data) - 1)
            gf     = self.ghost_data[g_idx]
            gx_m   = map_x + gf["x"] * scale
            gy_m   = map_y + gf["y"] * scale
            gcol   = 5 if pyxel.frame_count % 8 < 5 else 13
            # 十字型でゴースト位置を表示
            pyxel.pset(int(gx_m),     int(gy_m),     gcol)
            pyxel.pset(int(gx_m) - 1, int(gy_m),     gcol)
            pyxel.pset(int(gx_m) + 1, int(gy_m),     gcol)
            pyxel.pset(int(gx_m),     int(gy_m) - 1, gcol)
            pyxel.pset(int(gx_m),     int(gy_m) + 1, gcol)
            pyxel.text(int(gx_m) + 2, int(gy_m) - 4, "G", gcol)
        # オンライン対戦相手をミニマップに表示（点滅で識別しやすく）
        peer_colors = [12, 11, 9, 14]
        for ci, (pid, pg) in enumerate(self.online_peers.items()):
            ox = map_x + pg.get("x", 0) * scale
            oy = map_y + pg.get("y", 0) * scale
            pcol = peer_colors[ci % len(peer_colors)]
            # 点滅させて自車と区別
            if pyxel.frame_count % 6 < 4:
                pyxel.rect(int(ox) - 1, int(oy) - 1, 3, 3, pcol)
            # IDの頭文字を脇に表示
            pyxel.text(int(ox) + 2, int(oy) - 3, pid[0].upper(), pcol)
        cx = map_x + self.car_world_x * scale
        cy = map_y + self.car_world_y * scale
        pyxel.rect(cx - 1, cy - 1, 3, 3, 8)
        
    def draw_game_scene(self):
        sky_color = 16 if self.is_night_mode else 6
        pyxel.rect(0, 0, pyxel.width, 80, sky_color)

        for c in sorted(self.clouds, key=lambda x: x["depth"]):
            scale = 0.5 + (c["depth"] * 0.5)

        self.draw_mode7_road()
        self.draw_walls_3d()   # 壁の立体描画
        # 遠い順（Z深度が大きい順）に描画するためにソートする
        def get_rival_z(rival):
            dx = rival.x - self.car_world_x
            dy = rival.y - self.car_world_y
            return dx * math.cos(self.car_angle) + dy * math.sin(self.car_angle)
            
        self.rivals.sort(key=get_rival_z, reverse=True)

        for rival in self.rivals:
            rival.draw_3d(self.car_world_x, self.car_world_y, self.car_angle)

        # ── ゴースト描画（タイムアタック時、ゴーストデータがある場合）──
        if (self.is_time_attack and self.ghost_enabled
                and self.ghost_data and self.start_timer == 0):
            sample  = max(1, getattr(self, 'ghost_sample', 1))
            g_idx   = min(self.ghost_frame_idx // sample, len(self.ghost_data) - 1)
            gf = self.ghost_data[g_idx]
            gx, gy, ga = gf["x"], gf["y"], gf["a"]
            # ゴーストの3D投影（RivalCarのdraw_3dと同じ式）
            horizon = 80; cam_z = 40.0; fov = 1.3; sf = 0.02
            sn2 = math.sin(self.car_angle); cs2 = math.cos(self.car_angle)
            dx = gx - self.car_world_x; dy = gy - self.car_world_y
            lz = dx*cs2 + dy*sn2; lx = -dx*sn2 + dy*cs2
            if lz > 0.5:
                dy_s = (cam_z * 100.0 * sf) / lz
                sx = pyxel.width/2 + lx*100.0/(fov*lz)
                sy = horizon + dy_s
                scale = dy_s / 76.92
                if 0.08 < scale < 5.0:
                    # 半透明の影シルエットのみ（色=5 暗いグレー）
                    gu = gf.get("u", 49); gw = gf.get("w", 0)
                    ghost_col = 5   # ゴーストは暗いグレーのシルエット
                    pyxel.pal(195, ghost_col)
                    for c in range(16):
                        if c != 0:          # 透過色(229)以外を全部ゴースト色に
                            pyxel.pal(c, ghost_col)
                    bx_ = sx - abs(gu)/2
                    by_ = sy - 12 - 12*scale
                    pyxel.blt(bx_, by_, 0, 0, gw, gu, 24, 229, scale=scale)
                    pyxel.pal()   # パレット戻す
        car_draw_y = pyxel.height - 50

        # 土煙描画 (車体の描画の奥側)
        for p in self.dirt_particles:
            base_col = p.get("col", 9)
            col = base_col if p["life"] > p["max_life"]//2 else 5
            r = max(1, int(p["size"]))
            pyxel.circ(p["x"], p["y"], r, col)

        # スリップストリーム集中線エフェクト描画（ドーナツ状・内側→外側）
        if getattr(self, 'slipstream_particles', []):
            cx_ss = pyxel.width  // 2
            cy_ss = pyxel.height // 2 + 10
            W_ss  = pyxel.width
            H_ss  = pyxel.height
            for wp in self.slipstream_particles:
                t = wp["life"] / wp["max_life"]
                col = 7 if t > 0.65 else (12 if t > 0.35 else 5)
                ang = wp["ang"]
                ca, sa = math.cos(ang), math.sin(ang)
                # 楕円補正（遠近感）。外径は画面端を超えるくらい大きく
                ri = wp["r_inner"]
                ro = wp["r_outer"]
                x1 = int(cx_ss + ca * ri)
                y1 = int(cy_ss + sa * ri * 0.5)
                x2 = int(cx_ss + ca * ro)
                y2 = int(cy_ss + sa * ro * 0.5)
                # 画面内にある線分のみ描画（クリッピング不要、pyxelが自動で切る）
                pyxel.line(x1, y1, x2, y2, col)

        # スリップストリーム発動中のUI表示
        if getattr(self, 'slipstream_active', False):
            sx_ui = pyxel.width // 2
            col_ss = 12 if (pyxel.frame_count % 8) < 4 else 7
            #pyxel.text(sx_ui - 30, 90, "SLIPSTREAM!!", col_ss)

        if self.is_night_mode:
            swing = -30 if (pyxel.btn(pyxel.KEY_LEFT) or pyxel.btn(pyxel.KEY_A)) else 30 if (pyxel.btn(pyxel.KEY_RIGHT) or pyxel.btn(pyxel.KEY_D)) else 0
            
            # 車のグラフィック変更によるライト起点のオフセット
            offset_x = 0
            if self.u == -50: offset_x = -2
            elif self.u == 50: offset_x = 2
            
            left_lx = pyxel.width/2 - 10 + offset_x
            right_lx = pyxel.width/2 + 10 + offset_x
            light_y_base = car_draw_y + 10 # 車のヘッドライト付近のY座標
            
            for i in range(1, 12):
                w = i * 2
                lx = left_lx + (swing * (i / 12))
                rx = right_lx + (swing * (i / 12))
                ly = light_y_base - (i * 4) # 奥に向かって描画
                
                # 左ライト
                pyxel.line(lx - w, ly, lx + w, ly, 10)
                if i < 6: pyxel.line(lx - w//2, ly, lx + w//2, ly, 7)
                
                # 右ライト
                pyxel.line(rx - w, ly, rx + w, ly, 10)
                if i < 6: pyxel.line(rx - w//2, ly, rx + w//2, ly, 7)

        # 自車の影（地面密着・楕円）
        shadow_cx = pyxel.width / 2
        shadow_cy = car_draw_y + 22   # 車底面付近
        pyxel.elli(int(shadow_cx - 20), int(shadow_cy - 4), 40, 8, 0)

        pyxel.pal(195, self.car_color)
        pyxel.blt(pyxel.width/2 - 25, car_draw_y, 0, 0, self.w, self.u, 24, 229)
        if self.is_braking:
            pyxel.rect(pyxel.width/2 - 14, car_draw_y + 15, 5, 2, 8)
            pyxel.rect(pyxel.width/2 + 9, car_draw_y + 15, 5, 2, 8)
        pyxel.pal()


        # ── オンライン対戦相手の描画 ──
        peer_items = list(self.online_peers.items())
        def _peer_z(item):
            pg = item[1]
            dx = pg.get("x", 0) - self.car_world_x
            dy = pg.get("y", 0) - self.car_world_y
            return dx * math.cos(self.car_angle) + dy * math.sin(self.car_angle)
        peer_items.sort(key=_peer_z, reverse=True)

        horizon      = 80
        cam_z        = 40.0
        fov          = 1.3
        scale_factor = 0.02
        sn = math.sin(self.car_angle)
        cs = math.cos(self.car_angle)
        peer_colors = [12, 11, 9, 14]
        for ci, (pid, pg) in enumerate(peer_items):
            px_w = pg.get("x", 0)
            py_w = pg.get("y", 0)
            pu   = pg.get("u", 49)   # 向きスプライトu
            pw   = pg.get("w", 0)    # 向きスプライトw
            dx   = px_w - self.car_world_x
            dy   = py_w - self.car_world_y
            local_z =  dx * cs + dy * sn
            local_x = -dx * sn + dy * cs
            if local_z > 0.1:
                dy_screen = (cam_z * 100.0 * scale_factor) / local_z
                screen_y  = horizon + dy_screen
                screen_x  = pyxel.width / 2 + (local_x * 100.0) / (fov * local_z)
                scale_s   = dy_screen / 76.92
                if 0.08 < scale_s < 5.0:
                    pcol = peer_colors[ci % len(peer_colors)]
                    # 影: draw_3d と同じ計算式
                    shadow_w = 40 * scale_s
                    shadow_h = 10 * scale_s
                    pyxel.elli(screen_x - shadow_w / 2,
                               screen_y - shadow_h / 2,
                               shadow_w, shadow_h, 0)
                    # 車体: draw_3d と同じ座標式
                    # base_x: スプライト幅(abs(pu))の中心を screen_x に合わせる
                    base_y = screen_y - 12 - (12 * scale_s)
                    base_x = screen_x - (abs(pu) / 2)
                    # パレット: 195番のみ相手色に置き換え（他は元の色を保持）
                    pyxel.pal(195, pcol)
                    pyxel.blt(base_x, base_y, 0, 0, pw, pu, 24, 229,
                              scale=scale_s)
                    pyxel.pal()   # 1色だけ変えたので pal() でリセットで十分
                    # IDラベル
                    if scale_s > 0.25:
                        lx = int(screen_x) - len(pid[:4]) * 2
                        ly = int(base_y) - 7
                        pyxel.text(lx, ly, pid[:4], pcol)


        if self.start_timer > 0:
            cx, cy = pyxel.width / 2, 50
            pyxel.rectb(cx - 25, cy - 10, 50, 20, 7)
            pyxel.rect(cx - 24, cy - 9, 48, 18, 0)
            col_l = 11 if 0 <= self.start_timer <= 10 else 8 if 10 < self.start_timer <= 200 else 5
            col_m = 11 if 0 <= self.start_timer <= 10 else 8 if 10 < self.start_timer <= 140 else 5
            col_r = 11 if 0 <= self.start_timer <= 10 else 8 if 10 < self.start_timer <= 80 else 5
            pyxel.sounds[1].volumes[0] = 7
            if self.start_timer in (200, 140, 80): pyxel.play(1, 1)
            elif self.start_timer == 10:
                pyxel.sounds[1].notes[0] = 48
                pyxel.play(1, 1)
            pyxel.circ(cx - 15, cy, 6, col_l)
            pyxel.circ(cx, cy, 6, col_m)
            pyxel.circ(cx + 15, cy, 6, col_r)

            # ロケットスタート準備中の表示
            if self.is_rocket_start:
                rc = 9 if (pyxel.frame_count % 10) < 5 else 10
                pyxel.text(cx - 38, cy + 14, "!! ROCKET READY !!", rc)
            elif self.start_timer <= 100:
                pyxel.text(cx - 34, cy + 14, "HOLD ACCEL NOW!", 6)

        if self.rocket_text_timer > 0:
            pyxel.text(pyxel.width/2 - 35, 90, "ROCKET START!!", pyxel.frame_count % 16)
            self.rocket_text_timer -= 1
        if self.stall_timer > 0:
            pyxel.text(pyxel.width/2 - 30, 90, "ENGINE STALL!", 8)

        if not self.is_goal:
            self.draw_speedometer()
            ui_col = 10 if self.is_night_mode else 0
            current_lap_time = self.lap_frame_count / 30.0

            if self.is_time_attack:
                pyxel.text(10, 10, f"LAP: {self.current_lap}  [TIME ATTACK]", ui_col)
            else:
                pyxel.text(10, 10, f"LAP: {self.current_lap}/{self.goal_laps}", ui_col)
            pyxel.text(10, 20, f"TIME: {current_lap_time:.2f}s", ui_col)
            pyxel.text(10, 30, f"LAST: {self.last_lap_time:.2f}s", ui_col)

            # ── オンライン順位パネル ──
            is_online = (self.online_client and self.online_client.connected
                         and self.online_peers)
            if is_online:
                # 自分と全ピアの進捗スコアを計算（周回数×コース長 + コース進捗）
                n_pts = len(self.smooth_points) if self.smooth_points else 1
                my_score = (getattr(self, 'current_lap', 1) - 1) * n_pts \
                           + getattr(self, 'car_progress', 0)
                my_goal  = getattr(self, 'is_goal', False)

                entries = [("YOU", my_score, my_goal, 8)]  # col=赤
                peer_colors = [12, 11, 9, 14]
                for ci, (pid, pg) in enumerate(self.online_peers.items()):
                    p_lap  = pg.get("lap", 1)
                    p_prog = pg.get("progress", 0)
                    p_goal = pg.get("is_goal", False)
                    p_score = (p_lap - 1) * n_pts + p_prog
                    entries.append((pid[:4].upper(), p_score, p_goal,
                                    peer_colors[ci % 4]))

                # ゴール済みは最上位、未ゴールはスコア降順
                entries.sort(key=lambda e: (not e[2], -e[1]))

                # パネル描画
                W = pyxel.width
                px_r = W - 68; py_r = 20
                panel_w = 62; row_h = 10
                panel_h = len(entries) * row_h + 8
                pyxel.rect(px_r - 2, py_r - 2, panel_w + 4, panel_h + 4, 0)
                pyxel.rectb(px_r - 2, py_r - 2, panel_w + 4, panel_h + 4, 5)

                suffix = ["ST", "ND", "RD"] + ["TH"] * 10
                for rank, (name, score, goal, col) in enumerate(entries):
                    ry = py_r + 4 + rank * row_h
                    rank_str = f"{rank+1}{suffix[rank]}"
                    goal_mark = "*" if goal else " "
                    label = f"{goal_mark}{rank_str} {name}"
                    # 自分の行は背景ハイライト
                    if name == "YOU":
                        pyxel.rect(px_r - 1, ry - 1, panel_w + 2, row_h, 1)
                    pyxel.text(px_r, ry, label, col)

            self.draw_minimap()
        else:
            total_cars = len(self.rivals) + 1
            s = "CONGRATULATIONS! GOAL!!"
            x_txt = pyxel.width / 2 - len(s) * 2
            box_h = 90 if not self.is_time_attack else 65
            pyxel.rect(x_txt - 10, pyxel.height / 2 - 40, len(s) * 4 + 20, box_h, 0)
            pyxel.text(x_txt, pyxel.height / 2 - 35, s, 10)

            if not self.is_time_attack:
                # レースモード：順位を大きく表示
                rank_col = 10 if self.goal_rank == 1 else (9 if self.goal_rank == 2 else 7)
                rank_s = f"FINISH: {self.goal_rank} / {total_cars}"
                if self.goal_rank == 1:
                    rank_col = 10 if (pyxel.frame_count % 20) < 10 else 9
                pyxel.text(x_txt + 15, pyxel.height / 2 - 18, rank_s, rank_col)
                best_txt = f"{self.best_lap_time:.2f}s" if self.best_lap_time else "---"
                pyxel.text(x_txt + 10, pyxel.height / 2 - 6, f"BEST LAP: {best_txt}", 6)

                # 賞金表示
                prize_y = pyxel.height // 2 + 6
                # 基本賞金
                base_col = 10 if self.prize_anim_phase >= 1 else 5
                pyxel.text(x_txt + 10, prize_y, f"PRIZE: {self.prize_amount} CR", base_col)
                # クリーンレースボーナス
                if self.collision_count == 0:
                    bonus_col = 9 if self.prize_anim_phase >= 2 else 5
                    pyxel.text(x_txt + 10, prize_y + 9, "CLEAN RACE BONUS: +50%", bonus_col)
                    total_y = prize_y + 18
                else:
                    total_y = prize_y + 9
                # 合計獲得クレジット（アニメーション中）
                if self.prize_anim_phase >= 1:
                    anim_col = 10 if (pyxel.frame_count % 10) < 5 else 9
                    total_col = anim_col if self.prize_anim_phase < 3 else 10
                    pyxel.text(x_txt + 10, total_y, f"EARNED: {self.prize_display} CR", total_col)
                # 所持クレジット合計（完了後）
                if self.prize_anim_phase == 3:
                    pyxel.text(x_txt + 10, total_y + 9, f"TOTAL : {self.credits} CR", 7)

                pyxel.text(x_txt + 7, pyxel.height / 2 + 8 + 35, "PUSH 'R' TO RESTART", 6)

            # ── オンライン対戦ゴール順位パネル ──
            is_online_race = (self.online_client and self.online_client.connected)
            if is_online_race and not self.is_time_attack:
                finish_order = getattr(self, 'online_finish_order', [])
                W, H = pyxel.width, pyxel.height
                px_r = W - 72; py_r = 10
                panel_w = 66
                row_h = 10
                panel_h = max(len(finish_order), 1) * row_h + 18

                pyxel.rect(px_r - 2, py_r - 2, panel_w + 4, panel_h + 4, 0)
                pyxel.rectb(px_r - 2, py_r - 2, panel_w + 4, panel_h + 4, 10)
                pyxel.text(px_r + 2, py_r + 2, "FINISH ORDER", 10)

                suffix = ["ST", "ND", "RD"] + ["TH"] * 10
                peer_colors = [10, 9, 7, 6, 5]
                for i, (pid, label) in enumerate(finish_order):
                    ry = py_r + 14 + i * row_h
                    rank_str = f"{i+1}{suffix[min(i,3)]}"
                    is_me = (pid == self.online_my_id)
                    col = peer_colors[min(i, len(peer_colors)-1)]
                    if is_me:
                        pyxel.rect(px_r - 1, ry - 1, panel_w + 2, row_h, 1)
                        col = 10 if i == 0 else col
                    disp_name = "YOU" if is_me else label
                    pyxel.text(px_r + 2, ry, f"{rank_str} {disp_name}", col)

                if not finish_order:
                    pyxel.text(px_r + 2, py_r + 14, "Waiting...", 5)

                # Rキーでロビーへ戻るヒント
                hint = "R: BACK TO LOBBY"
                pyxel.text(px_r + (panel_w - len(hint)*4)//2,
                           py_r + panel_h - 4, hint,
                           10 if (pyxel.frame_count // 15) % 2 == 0 else 7)
            else:
                # タイムアタックモード：ベストラップを表示
                if self.is_new_record:
                    col = 7 if (pyxel.frame_count % 20) < 10 else 10
                    pyxel.text(x_txt + 7, pyxel.height / 2 - 18, f"NEW RECORD: {self.best_lap_time:.2f}s", col)
                else:
                    best_txt = f"{self.best_lap_time:.2f}s" if self.best_lap_time else "---"
                    pyxel.text(x_txt + 7, pyxel.height / 2 - 18, f"BEST LAP: {best_txt}", 10)

                pyxel.text(x_txt + 7, pyxel.height / 2 + 8, "PUSH 'R' TO RESTART", 6)

    def draw_pause_overlay(self):
        W, H = pyxel.width, pyxel.height
        # 暗幕（隔行塗りつぶしで半透明感）
        for yy in range(0, H, 2):
            pyxel.line(0, yy, W, yy, 0)

        if self.pause_quit_confirm:
            dw, dh = 164, 58
            dx, dy = (W - dw) // 2, (H - dh) // 2
            pyxel.rect(dx, dy, dw, dh, 0)
            pyxel.rectb(dx, dy, dw, dh, 8)
            pyxel.text(dx + (dw - 72) // 2, dy + 8,  "QUIT THIS RACE?", 8)
            pyxel.text(dx + (dw - 96) // 2, dy + 22, "All progress will be lost.", 5)
            blink = (pyxel.frame_count // 12) % 2 == 0
            pyxel.text(dx + 16, dy + 38, "SPACE / Y : YES", 8 if blink else 7)
            pyxel.text(dx + 96, dy + 38, "ESC/N: NO", 6)
            return

        mw, mh = 150, 102
        mx, my = (W - mw) // 2, (H - mh) // 2
        pyxel.rect(mx, my, mw, mh, 0)
        pyxel.rectb(mx, my, mw, mh, 7)
        pyxel.rect(mx, my, mw, 14, 1)
        pyxel.text(mx + (mw - 24) // 2, my + 4, "PAUSED", 10)

        items = [("RESUME RACE", 10), ("RETRY RACE", 11), ("QUIT TO MENU", 8)]
        for i, (label, col) in enumerate(items):
            iy = my + 20 + i * 22
            if i == self.pause_focus:
                pyxel.rect(mx + 8, iy - 1, mw - 16, 18, 1)
                pyxel.rectb(mx + 8, iy - 1, mw - 16, 18, 10)
                if (pyxel.frame_count // 8) % 2 == 0:
                    pyxel.text(mx + 12, iy + 4, ">", 10)
                col = 10
            pyxel.text(mx + 22, iy + 4, label, col)

        pyxel.text(mx + (mw - 80) // 2, my + mh - 10, "W/S: MOVE  SPACE: OK", 5)

    def draw_confetti(self, x, y, size, col, angle):
        rad = math.radians(angle)
        s, c = math.sin(rad), math.cos(rad)
        half = size / 2
        pts = [
            (-half * c - half * s, -half * s + half * c),
            ( half * c - half * s,  half * s + half * c),
            ( half * c + half * s,  half * s - half * c),
            (-half * c + half * s, -half * s - half * c)
        ]
        for i in range(4):
            x1, y1 = x + pts[i][0], y + pts[i][1]
            x2, y2 = x + pts[(i + 1) % 4][0], y + pts[(i + 1) % 4][1]
            pyxel.line(x1, y1, x2, y2, col)
        pyxel.pset(x, y, col)

    def draw_title_screen(self):
        for i in range(10):
            y = (pyxel.frame_count * 2 + i * 20) % pyxel.height
            pyxel.line(0, y, pyxel.width, y, 1)
        pyxel.text(pyxel.width/2 - 40, 70, "REAL DRIVING SIMULATER", 10)
        pyxel.blt(0, 40, 2, 0, 0, 255, 30, 229, scale=0.7)
        if (pyxel.frame_count // 15) % 2 == 0:
            pyxel.text(pyxel.width/2 - 30, 100, "PUSH SPACE KEY", 7)

    def draw_menu_screen(self):
        W, H = pyxel.width, pyxel.height
        # 背景
        for i in range(0, H, 4):
            pyxel.line(0, i, W, i, 1 if i % 8 == 0 else 0)

        # タイトルロゴ
        pyxel.blt(0, 8, 2, 0, 0, 255, 30, 229, scale=0.55)

        # メニューパネル
        panel_w, panel_h = 160, 110
        px = (W - panel_w) // 2
        py = 52
        pyxel.rect(px, py, panel_w, panel_h, 0)
        pyxel.rectb(px, py, panel_w, panel_h, 7)

        menu_items = [
            ("RACE",      7),
            ("CUSTOMIZE", 14),
            ("STATUS",    11),
            ("OPTIONS",   6),
            ("ONLINE",    12),   # ← 追加
        ]
        item_h = 20
        for i, (label, col) in enumerate(menu_items):
            iy = py + 10 + i * item_h
            if i == self.menu_focus:
                # フォーカス強調背景
                pyxel.rect(px + 6, iy - 2, panel_w - 12, item_h - 2, 1)
                pyxel.rectb(px + 6, iy - 2, panel_w - 12, item_h - 2, 10)
                # カーソル矢印（点滅）
                if (pyxel.frame_count // 8) % 2 == 0:
                    pyxel.text(px + 10, iy + 2, ">", 10)
                col_draw = 10
            else:
                col_draw = col
            pyxel.text(px + 20, iy + 2, label, col_draw)

        # 操作ヒント
        pyxel.text((W - 80) // 2, py + panel_h + 6, "W/S: MOVE   SPACE: SELECT", 5)
        pyxel.text((W - 36) // 2, py + panel_h + 14, "ESC: BACK", 5)

    def draw_options_screen(self):
        W, H = pyxel.width, pyxel.height
        for i in range(0, H, 4):
            pyxel.line(0, i, W, i, 1 if i % 8 == 0 else 0)

        # タイトルバー
        pyxel.rect(0, 0, W, 14, 1)
        pyxel.text(W // 2 - 20, 4, "OPTIONS", 10)

        panel_w, panel_h = 210, 130
        px = (W - panel_w) // 2
        py = 22

        pyxel.rect(px, py, panel_w, panel_h, 0)
        pyxel.rectb(px, py, panel_w, panel_h, 7)

        at_mt = "AT (AUTO)" if self.is_automatic else "MT (MANUAL)"

        # MAP DETAIL ラベル生成
        detail_labels = {1: "ULTRA FINE", 2: "FINE", 3: "NORMAL", 4: "ROUGH"}
        detail_lbl = detail_labels.get(self.map_pixel_size, "FINE")

        # WHEEL SENS ラベル
        sens = getattr(self, 'wheel_sensitivity', 5)
        sens_lbl = f"{sens:2d} / 10"

        # オプション項目: 0=TRANSMISSION, 1=MAP DETAIL, 2=WHEEL SENS, 3=CONTROLS, 4=BACK
        opt_items = [
            (f"TRANSMISSION: {at_mt}", 10),
            (f"MAP DETAIL:   {detail_lbl}", 11),
            (f"WHEEL SENS:   {sens_lbl}", 12),
            ("CONTROLS",                6),
            ("BACK",                    6),
        ]
        item_h = 20
        for i, (label, col) in enumerate(opt_items):
            iy = py + 10 + i * item_h
            if i == self.opt_focus:
                pyxel.rect(px + 6, iy - 2, panel_w - 12, item_h - 2, 1)
                pyxel.rectb(px + 6, iy - 2, panel_w - 12, item_h - 2, 10)
                if (pyxel.frame_count // 8) % 2 == 0:
                    pyxel.text(px + 10, iy + 4, ">", 10)
                col_draw = 10
            else:
                col_draw = col
            pyxel.text(px + 20, iy + 4, label, col_draw)

        # MAP DETAIL 選択中: スライダーUI
        if self.opt_focus == 1:
            bar_y = py + 10 + 1 * item_h + item_h - 2
            bar_x = px + 20
            dot_w = 12
            for d in range(4):
                dx = bar_x + 72 + d * (dot_w + 2)
                filled = (d < self.map_pixel_size)
                pyxel.rect(dx, bar_y + 1, dot_w, 6, 11 if filled else 1)
                pyxel.rectb(dx, bar_y + 1, dot_w, 6, 11 if filled else 5)

        # WHEEL SENS 選択中: 10段スライダーUI
        if self.opt_focus == 2:
            bar_y = py + 10 + 2 * item_h + item_h - 2
            bar_x = px + 20
            dot_w = 14
            for d in range(10):
                dx = bar_x + d * (dot_w + 1)
                filled = (d < sens)
                col_d = 12 if filled else 1
                pyxel.rect(dx, bar_y + 1, dot_w, 6, col_d)
                pyxel.rectb(dx, bar_y + 1, dot_w, 6, 12 if filled else 5)

        pyxel.text((W - 80) // 2, H - 10, "W/S: MOVE  A/D: ADJUST  ESC: BACK", 5)

        # CONTROLS インフォオーバーレイ
        if self.opt_focus == 3:
            ow, oh = 220, 100
            ox = (W - ow) // 2
            oy = (H - oh) // 2 + 20
            pyxel.rect(ox, oy, ow, oh, 0)
            pyxel.rectb(ox, oy, ow, oh, 11)
            pyxel.text(ox + (ow - 56) // 2, oy + 5, "--- CONTROLS ---", 11)
            lines = [
                ("ARROW / A or D",       "STEER",          6, 7),
                ("W / UP",               "ACCELERATE",     6, 7),
                ("S / DOWN",             "BRAKE",          6, 7),
                ("MT: Q / E",            "SHIFT UP/DOWN",  6, 7),
                ("ESC",                  "PAUSE",          6, 7),
                ("R  (pause)",           "RETURN TO MENU", 6, 7),
            ]
            for li, (key, desc, kc, dc) in enumerate(lines):
                lx = ox + 8
                ly = oy + 18 + li * 12
                pyxel.text(lx,      ly, key,  kc)
                pyxel.text(lx + 72, ly, desc, dc)

    def draw_status_screen(self):
        W, H = pyxel.width, pyxel.height
        # 背景グラデーション風ライン
        for i in range(0, H, 4):
            pyxel.line(0, i, W, i, 1 if i % 8 == 0 else 0)

        # ── タイトルバー ──
        pyxel.rect(0, 0, W, 14, 1)
        pyxel.text(W // 2 - 28, 4, "PLAYER STATUS", 10)

        # ── メインパネル ──
        px, py = 18, 20
        pw, ph = W - 36, H - 36
        pyxel.rect(px, py, pw, ph, 0)
        pyxel.rectb(px, py, pw, ph, 7)

        # ── クレジットブロック（上部）──
        bx, by = px + 8, py + 8
        pyxel.rectb(bx, by, pw - 16, 22, 10)
        pyxel.rect(bx + 1, by + 1, pw - 18, 20, 1)
        cr_label = "CREDITS"
        cr_val   = f"{self.credits:,} CR"
        pyxel.text(bx + 4,  by + 4,  cr_label, 6)
        # クレジット値を大きめに（4文字×4px）
        col_cr = 10 if (pyxel.frame_count // 20) % 2 == 0 else 9
        pyxel.text(bx + pw - 20 - len(cr_val) * 4, by + 4, cr_val, col_cr)

        # ── 統計ブロック ──
        sy = by + 30
        line_h = 14

        # 走行時間を mm:ss 形式に変換
        total_sec = int(self.stats.get("total_frames", 0) / 30)
        t_h   = total_sec // 3600
        t_m   = (total_sec % 3600) // 60
        t_s   = total_sec % 60
        time_str = f"{t_h:02d}h {t_m:02d}m {t_s:02d}s"

        # 走行距離はワールド単位→画面表示用スケール (約1単位≒1m想定で km 換算)
        dist_km = self.stats.get("total_distance", 0.0) * 0.001
        dist_str = f"{dist_km:.2f} km"

        rows = [
            ("RACES ENTERED",    f"{self.stats.get('race_count', 0)}"),
            ("1ST PLACE WINS",   f"{self.stats.get('first_count', 0)}"),
            ("WIN RATE",         f"{(self.stats.get('first_count',0)/max(self.stats.get('race_count',1),1)*100):.1f}%"),
            ("TOTAL DISTANCE",   dist_str),
            ("TOTAL DRIVE TIME", time_str),
            ("TOTAL EARNED CR",  f"{self.stats.get('total_credits', 0):,} CR"),
        ]

        for i, (label, val) in enumerate(rows):
            ry = sy + i * line_h
            # 奇数行をわずかに薄い背景で
            if i % 2 == 0:
                pyxel.rect(px + 4, ry - 1, pw - 8, line_h - 2, 1)
            label_col = 6
            val_col   = 7
            # 特別な行を強調
            if label == "1ST PLACE WINS":
                val_col = 10
            elif label == "TOTAL EARNED CR":
                val_col = 9

            pyxel.text(px + 8,  ry + 2, label, label_col)
            pyxel.text(px + pw - 8 - len(val) * 4, ry + 2, val, val_col)
            # 区切り線
            pyxel.line(px + 4, ry + line_h - 3, px + pw - 5, ry + line_h - 3, 1)

        # ── フッター ──
        pyxel.text(W // 2 - 28, H - 12, "ESC: BACK TO MENU", 5)

    def draw_mode_select_screen(self):
        cx = pyxel.width // 2 - 90
        cy = pyxel.height // 2 - 50
        pyxel.rectb(cx, cy, 180, 100, 10)
        pyxel.text(cx + 65, cy + 8, "SELECT MODE", 10)

        # TIME ATTACK
        ta_col = 10 if self.is_time_attack else 5
        ta_border = 9 if self.is_time_attack else 5
        pyxel.rectb(cx + 10, cy + 28, 70, 38, ta_border)
        if self.is_time_attack:
            pyxel.rect(cx + 11, cy + 29, 68, 36, 1)
        pyxel.text(cx + 16, cy + 34, "TIME ATTACK", ta_col)
        pyxel.text(cx + 14, cy + 44, "Solo / Best Lap", 6)
        pyxel.text(cx + 18, cy + 54, "No lap limit", 5)

        # RACE
        rc_col = 10 if not self.is_time_attack else 5
        rc_border = 9 if not self.is_time_attack else 5
        pyxel.rectb(cx + 100, cy + 28, 70, 38, rc_border)
        if not self.is_time_attack:
            pyxel.rect(cx + 101, cy + 29, 68, 36, 1)
        pyxel.text(cx + 116, cy + 34, "RACE", rc_col)
        pyxel.text(cx + 104, cy + 44, "vs Rivals", 6)
        pyxel.text(cx + 102, cy + 54, "Fixed lap count", 5)

        pyxel.text(cx + 20, cy + 74, "A/D: SELECT", 6)

        blink_col = 10 if (pyxel.frame_count // 15) % 2 == 0 else 7
        pyxel.text(cx + 90, cy + 74, "SPACE: NEXT", blink_col)
        pyxel.text(cx + 155, cy + 74, "ESC", 6)

    def draw_course_select_screen(self):
        W, H = pyxel.width, pyxel.height
        pyxel.rect(0, 0, W, H, 0)

        cd = self.COURSES[self.selected_course]
        course_name = cd["name"]
        total = len(self.COURSES)

        # ── タイトルバー ──
        pyxel.rect(0, 0, W, 14, 1)
        pyxel.text(W // 2 - 36, 4, "SELECT COURSE", 10)

        # ── コース名 + ページ ──
        label = f"< {course_name}  ({self.selected_course+1}/{total}) >"
        pyxel.text((W - len(label) * 4) // 2, 18, label, 14)

        # ── 大きなマップ（中央） ──
        map_size = 140
        map_x = (W - map_size) // 2 - 16
        map_y = 28

        pyxel.rect(map_x, map_y, map_size, map_size, 0)
        pyxel.rectb(map_x - 1, map_y - 1, map_size + 2, map_size + 2, 5)
        pyxel.rectb(map_x - 2, map_y - 2, map_size + 4, map_size + 4, 7)

        scale = map_size / 256.0
        pts = self.smooth_points
        # コース外縁を太く（3ピクセル分オフセット描画）
        for dx_off, dy_off in ((0,0),(1,0),(0,1)):
            for i in range(len(pts)):
                p1, p2 = pts[i], pts[(i+1) % len(pts)]
                pyxel.line(map_x + p1[0]*scale + dx_off,
                           map_y + p1[1]*scale + dy_off,
                           map_x + p2[0]*scale + dx_off,
                           map_y + p2[1]*scale + dy_off, cd["col_mid"])
        # スタートマーカー
        sx = map_x + cd["start_pos"][0] * scale
        sy = map_y + cd["start_pos"][1] * scale
        pyxel.circ(sx, sy, 3, 8)
        pyxel.rectb(int(sx)-3, int(sy)-3, 7, 7, 10)

        # ── 右側パネル ──
        rx = map_x + map_size + 8
        ry = map_y + 4

        best_txt = f"BEST:{self.best_lap_time:.2f}s" if self.best_lap_time else "BEST:---.--s"
        pyxel.text(rx, ry, best_txt, 10)

        if not self.is_time_attack:
            pyxel.text(rx, ry + 14, f"LAPS: {self.goal_laps}", 11)
            pyxel.text(rx, ry + 22, "W/S:ADJ", 5)
        else:
            pyxel.text(rx, ry + 14, "TIME", 9)
            pyxel.text(rx, ry + 22, "ATTACK", 9)

        # [E] MAKER ボタン
        pyxel.rect(rx - 2, ry + 36, 46, 12, 1)
        pyxel.rectb(rx - 2, ry + 36, 46, 12, 14)
        pyxel.text(rx, ry + 39, "[E] MAKER", 14)

        # ── 操作ヒント ──
        pyxel.text(4, H - 16, "A/D: COURSE", 6)
        blink_col = 10 if (pyxel.frame_count // 15) % 2 == 0 else 7
        pyxel.text((W - 72) // 2, H - 10, "SPACE: SELECT", blink_col)
        pyxel.text(W - 44, H - 16, "ESC: BACK", 5)
        if self.selected_course >= 4:
            pyxel.text(4, H - 8, "[DEL]:DELETE", 8)
        if self.is_time_attack:
            pyxel.text(W - 56, H - 8, "[R]:RANKING", 9)

        # 共有ヒント（右側パネル下）
        pyxel.rect(rx - 2, ry + 52, 60, 42, 0)
        pyxel.rectb(rx - 2, ry + 52, 60, 42, 5)
        pyxel.text(rx, ry + 55, "SHARE:", 5)
        pyxel.text(rx, ry + 63, "[X] EXPORT", 6)
        pyxel.text(rx, ry + 71, "[I] IMPORT", 6)
        if self.is_time_attack:
            pyxel.text(rx, ry + 79, "[G]ghost", 9)
            pyxel.text(rx + 32, ry + 79, "[L]load", 9)

        # 共有メッセージ（画面中央下部、タイマーが残っている間表示）
        if self._share_msg_timer > 0:
            fade = min(self._share_msg_timer, 30) / 30.0
            mcol = 10 if fade > 0.5 else 5
            msg = self._share_msg[:36]   # 画面幅に収まるように切り詰め
            mx = (W - len(msg) * 4) // 2
            pyxel.rect(mx - 4, H // 2 - 8, len(msg) * 4 + 8, 14, 0)
            pyxel.rectb(mx - 4, H // 2 - 8, len(msg) * 4 + 8, 14, mcol)
            pyxel.text(mx, H // 2 - 4, msg, mcol)

        # ── 削除確認ダイアログ ──
        if self.cs_del_confirm:
            cn = self.COURSES[self.selected_course]["name"]
            dw, dh = 180, 52
            ddx, ddy = (W - dw) // 2, (H - dh) // 2
            pyxel.rect(ddx, ddy, dw, dh, 0)
            pyxel.rectb(ddx, ddy, dw, dh, 8)
            msg = f"DELETE '{cn}'?"
            pyxel.text(ddx + (dw - len(msg)*4) // 2, ddy + 8, msg, 8)
            pyxel.text(ddx + (dw - 84)//2, ddy + 20, "This cannot be undone!", 5)
            blink = (pyxel.frame_count // 12) % 2 == 0
            pyxel.text(ddx + 16, ddy + 34, "SPACE/Y : DELETE", 8 if blink else 7)
            pyxel.text(ddx + 104, ddy + 34, "ESC/N", 6)

    def draw_ranking_screen(self):
        W, H = pyxel.width, pyxel.height
        for i in range(0, H, 4):
            pyxel.line(0, i, W, i, 1 if i % 8 == 0 else 0)
        pyxel.rect(0, 0, W, 14, 1)
        cd  = self.COURSES[self.selected_course]
        hdr = f"TIME ATTACK RANKING  [{cd['name']}]"
        pyxel.text((W - len(hdr)*4) // 2, 4, hdr, 10)

        px, py = 36, 22
        pw, ph = W - 72, H - 48
        pyxel.rect(px, py, pw, ph, 0)
        pyxel.rectb(px, py, pw, ph, 7)

        ranking    = self.get_ta_ranking()
        medals     = ["1ST", "2ND", "3RD", "4TH", "5TH"]
        medal_cols = [10, 7, 9, 6, 5]

        if not ranking:
            msg = "NO RECORDS YET!"
            pyxel.text((W - len(msg)*4)//2, py + ph//2 - 4, msg, 5)
        else:
            row_h   = 20
            start_y = py + 12
            for i, t in enumerate(ranking):
                ry  = start_y + i * row_h
                col = medal_cols[i]
                if i == 0:
                    col = 10 if (pyxel.frame_count // 15) % 2 == 0 else 9
                rank_str = medals[i]
                time_str = f"{t:.3f}s"
                pyxel.rect(px + 6, ry - 2, pw - 12, row_h - 4, 1)
                pyxel.rectb(px + 6, ry - 2, pw - 12, row_h - 4, col)
                pyxel.text(px + 14, ry + 3, rank_str, col)
                pyxel.text(px + pw - 6 - len(time_str)*4, ry + 3, time_str, col)

        pyxel.text((W - 60)//2, H - 18, "ESC: BACK TO COURSE SELECT", 5)


    def draw_online_entry(self):
        """ルーム作成 or 参加入力画面"""
        W, H = pyxel.width, pyxel.height
        for i in range(0, H, 4):
            pyxel.line(0, i, W, i, 1 if i % 8 == 0 else 0)
        pyxel.rect(0, 0, W, 14, 1)
        pyxel.text((W - 60) // 2, 4, "ONLINE MATCH", 10)

        # Supabase未設定の警告
        if "your-project" in SUPABASE_URL or "your-anon-key" in SUPABASE_ANON_KEY:
            pyxel.rect(4, 16, W - 8, 10, 2)
            pyxel.text(8, 18, "! Set SUPABASE_URL & ANON_KEY in claude.py !", 8)

        blink = (pyxel.frame_count // 12) % 2 == 0

        # CREATE / JOIN ボタン
        btn_w, btn_h = 100, 30
        gap = 12
        bx  = (W - (btn_w * 2 + gap)) // 2
        by  = 28

        for i, (label, col) in enumerate([("CREATE ROOM", 10), ("JOIN ROOM", 11)]):
            bx_n = bx + i * (btn_w + gap)
            sel  = (self.online_entry_mode == i)
            bg   = 1 if sel else 0
            br   = col if sel else 5
            pyxel.rect(bx_n, by, btn_w, btn_h, bg)
            pyxel.rectb(bx_n, by, btn_w, btn_h, br)
            if sel and blink:
                pyxel.rectb(bx_n+1, by+1, btn_w-2, btn_h-2, br)
            tc = col if sel else 5
            pyxel.text(bx_n + (btn_w - len(label)*4)//2, by + 11, label, tc)

        py = by + btn_h + 14

        if self.online_entry_mode == 0:
            # CREATE モード
            pyxel.text(8, py, "A new Room ID will be generated.", 7)
            py += 10
            pyxel.text(8, py, "Share the ID with friends (up to 4).", 5)
        else:
            # JOIN モード
            if self.online_join_active:
                # テキスト入力モード中: テキストボックスをアクティブ表示
                pyxel.text(8, py, "Enter Room ID:", 10)
                py += 10
                iw = W - 16
                pyxel.rect(8, py, iw, 14, 1)
                pyxel.rectb(8, py, iw, 14, 10)
                pyxel.rectb(9, py+1, iw-2, 12, 10)
                txt = self.online_join_input + ("|" if blink else "")
                pyxel.text(12, py + 3, txt[:36], 10)
                py += 20
                pyxel.text(8, py, "Type Room ID  ENTER: Join  ESC: Cancel", 11)
            else:
                # 未アクティブ: テキストボックスはグレーアウト
                pyxel.text(8, py, "Enter Room ID:", 7)
                py += 10
                iw = W - 16
                pyxel.rect(8, py, iw, 14, 0)
                pyxel.rectb(8, py, iw, 14, 5)
                pyxel.text(12, py + 3, "Press ENTER to type...", 5)
                py += 20
                pyxel.text(8, py, "Select JOIN ROOM then press ENTER", 5)

        if self.online_join_active:
            pyxel.text((W - 44) // 2, H - 10, "ESC: CANCEL", 8)
        else:
            pyxel.text((W - 112) // 2, H - 20,
                       "A/D: SWITCH   ENTER: CONFIRM", 6)
            pyxel.text((W - 44) // 2, H - 10, "ESC: BACK", 5)

    def draw_online_lobby(self):
        """ロビー待機画面（ホスト/ゲスト共通）"""
        W, H = pyxel.width, pyxel.height
        for i in range(0, H, 4):
            pyxel.line(0, i, W, i, 1 if i % 8 == 0 else 0)

        blink = (pyxel.frame_count // 12) % 2 == 0

        # ── タイトルバー ──
        role = "HOST" if self.online_is_host else "GUEST"
        pyxel.rect(0, 0, W, 14, 1)
        hdr = f"ONLINE LOBBY  [{role}]"
        pyxel.text((W - len(hdr)*4) // 2, 4, hdr, 10 if self.online_is_host else 11)

        py = 18

        # ── 接続ステータス ──
        connected = self.online_client and self.online_client.connected
        scol = 11 if connected else 8
        pyxel.text(8, py, self.online_status, scol)
        py += 12

        # ── ルームID（コピー用に大きく） ──
        pyxel.rect(6, py, W - 12, 18, 0)
        pyxel.rectb(6, py, W - 12, 18, 5)
        pyxel.text(10, py + 2,  "Room ID:", 5)
        pyxel.text(10, py + 9, self.online_room_id, 10)
        py += 22

        # ── 参加者リスト ──
        peers = self.online_peers
        pyxel.text(8, py, f"Players  {len(peers)+1}/4", 7)
        py += 8
        # 自分
        you_col = 10 if self.online_is_host else 11
        pyxel.text(16, py, f"* {self.online_my_id}  (YOU{'  HOST' if self.online_is_host else ''})", you_col)
        py += 8
        for i, pid in enumerate(list(peers.keys())[:3]):
            pyxel.text(16, py, f"- {pid}", 6)
            py += 8
        py += 4

        # ── ホスト: レース設定パネル ──
        if self.online_is_host:
            pyxel.rect(6, py, W-12, 46, 0)
            pyxel.rectb(6, py, W-12, 46, 10)
            pyxel.text(10, py+2, "RACE SETTINGS  (A/D:course  W/S:laps  N:night)", 10)
            cd = self.COURSES[self.selected_course]
            night_str = "NIGHT" if self.is_night_mode else "DAY"
            pyxel.text(10, py+12, f"Course : {cd['name']}", 7)
            pyxel.text(10, py+21, f"Laps   : {self.goal_laps}    Time: {night_str}", 7)
            # コースミニプレビュー（4コース分インジケーター）
            for ci in range(4):
                cx_ = 10 + ci * 14
                col_ = 10 if ci == self.selected_course else 5
                pyxel.rectb(cx_, py+31, 12, 8, col_)
                name = self.COURSES[ci]["name"][:3]
                pyxel.text(cx_+1, py+33, name, col_)
            py += 50

            if connected:
                bc = 10 if blink else 9
                pyxel.rect((W-140)//2, py, 140, 16, bc)
                pyxel.rectb((W-140)//2, py, 140, 16, 7)
                pyxel.text((W-112)//2, py+4, "SPACE: START RACE FOR ALL", 0)
            else:
                pyxel.text(8, py, "Waiting for connection...", 5)

        # ── ゲスト: ホスト待ち表示 ──
        else:
            pyxel.rect(6, py, W-12, 46, 0)
            pyxel.rectb(6, py, W-12, 46, 11)
            pyxel.text(10, py+2, "WAITING FOR HOST...", 5)
            s = self.online_host_settings
            if s:
                pyxel.text(10, py+12, f"Course : {s.get('course_name','?')}", 7)
                night_str = "NIGHT" if s.get("night") else "DAY"
                pyxel.text(10, py+21, f"Laps   : {s.get('laps','?')}    Time: {night_str}", 7)
                if blink:
                    pyxel.text(10, py+33, "Host will start the race...", 11)
            else:
                pyxel.text(10, py+12, "Waiting for host settings...", 5)

        pyxel.text(8, H - 8, "ESC: LEAVE ROOM", 5)




    def draw_time_select_screen(self):
        W, H = pyxel.width, pyxel.height
        if self.is_night_mode:
            sky_top, sky_bot = 1, 2
        else:
            sky_top, sky_bot = 6, 12
        for y in range(H):
            t = y / H
            col = sky_bot if (y % 2 == 0 and t > 0.4) else sky_top
            pyxel.line(0, y, W, y, col)

        # ── タイトルバー ──
        pyxel.rect(0, 0, W, 14, 1)
        cd = self.COURSES[self.selected_course]
        hdr = f"TIME SELECT  [{cd['name']}]" if self.is_time_attack else f"TIME & DIFFICULTY  [{cd['name']}]"
        pyxel.text((W - len(hdr)*4) // 2, 4, hdr, 10)

        # フォーカスマップ（updateと完全に同じ定義）
        if self.is_time_attack:
            focus_map = {0: "day", 1: "night", 2: "ghost_on", 3: "ghost_off", 4: "start"}
        else:
            focus_map = {0: "day", 1: "night", 2: "easy", 3: "normal", 4: "hard", 5: "rivals", 6: "start"}
        cur_focus = self.time_sel_focus

        def is_focused(kind):
            return focus_map.get(cur_focus, "") == kind

        blink = (pyxel.frame_count // 8) % 2 == 0

        # ── DAY / NIGHT ボタン ──
        btn_w, btn_h = 90, 52
        gap = 12
        bx = (W - (btn_w * 2 + gap)) // 2
        by = 16

        for night in (False, True):
            kind = "night" if night else "day"
            bx_n = bx if not night else bx + btn_w + gap
            is_sel = (self.is_night_mode == night)
            focused = is_focused(kind)

            # 背景色: フォーカス=明るいハイライト / 選択済=テーマ色 / 通常=暗い
            if focused:
                bg_col  = 7   # 白に近い明るい背景
                brd_col = 10 if not night else 12
            elif is_sel:
                bg_col  = 2 if night else 9
                brd_col = 12 if night else 10
            else:
                bg_col  = 1
                brd_col = 5

            pyxel.rect(bx_n, by, btn_w, btn_h, bg_col)
            pyxel.rectb(bx_n, by, btn_w, btn_h, brd_col)

            # フォーカス枠: 太い二重枠を点滅させる
            if focused:
                fc = brd_col if blink else 0
                pyxel.rectb(bx_n + 1, by + 1, btn_w - 2, btn_h - 2, fc)
                pyxel.rectb(bx_n + 2, by + 2, btn_w - 4, btn_h - 4, fc)
            elif is_sel:
                pyxel.rectb(bx_n + 1, by + 1, btn_w - 2, btn_h - 2, brd_col)

            # アイコン描画
            cx_ = bx_n + btn_w // 2
            cy_ = by + 22
            if not night:
                pyxel.circ(cx_, cy_, 10, 10)
                pyxel.circ(cx_, cy_, 7, 9)
                for a in range(0, 360, 30):
                    r = math.radians(a)
                    pyxel.line(cx_ + math.cos(r)*13, cy_ + math.sin(r)*13,
                               cx_ + math.cos(r)*16, cy_ + math.sin(r)*16, 10)
                lbl, lcol = "DAY", 10
            else:
                # 月本体（明るい黄色系）
                pyxel.circ(cx_, cy_, 9, 7)
                # 欠け部分は空の色で塗る（ボタン背景色ではなく空色を使う）
                moon_bg = 2 if self.is_night_mode else 1  # 夜=紺、昼=黒
                pyxel.circ(cx_ + 5, cy_ - 3, 7, moon_bg)
                # 星（背景が白のフォーカス時は黒、それ以外は白）
                star_col = 0 if focused else 7
                for sx_, sy_ in [(cx_+14, cy_-7), (cx_+13, cy_+3), (cx_+6, cy_+10)]:
                    pyxel.pset(sx_, sy_, star_col)
                    pyxel.pset(sx_+1, sy_, star_col)
                lbl, lcol = "NIGHT", 12

            # ラベルテキスト
            lbl_col = 0 if focused else (lcol if is_sel else 5)
            pyxel.text(bx_n + (btn_w - len(lbl)*4)//2, by + 5, lbl, lbl_col)

            # 状態テキスト
            if focused and is_sel:
                st = "<<< SELECTED >>>" if blink else "< PRESS SPACE >"
                pyxel.text(bx_n + (btn_w - len(st)*4)//2, by + btn_h - 11, st, brd_col)
            elif focused:
                st = ">>> PRESS SPACE" if blink else "<<< PRESS SPACE"
                pyxel.text(bx_n + (btn_w - len(st)*4)//2, by + btn_h - 11, st, brd_col)
            elif is_sel:
                st = "* SELECTED *"
                pyxel.text(bx_n + (btn_w - len(st)*4)//2, by + btn_h - 11, st, brd_col)

        # ── 難易度選択パネル ──
        dy_top = by + btn_h + 6

        if not self.is_time_attack:
            DIFF_LABELS = ["EASY", "NORMAL", "HARD"]
            DIFF_KINDS  = ["easy", "normal", "hard"]
            DIFF_COLS   = [11, 10, 8]
            DIFF_DESC   = ["x0.5 Prize", "x0.75 Prize", "x1.0 Prize"]
            dpw, dph = W - 32, 42
            dpx = 16
            pyxel.rect(dpx, dy_top, dpw, dph, 0)
            pyxel.rectb(dpx, dy_top, dpw, dph, 7)
            pyxel.text(dpx + 4, dy_top + 3, "DIFFICULTY:", 7)

            slot_w = (dpw - 8) // 3
            for i, (lbl, dkind, dcol) in enumerate(zip(DIFF_LABELS, DIFF_KINDS, DIFF_COLS)):
                sx = dpx + 4 + i * slot_w
                sy = dy_top + 12
                sw = slot_w - 4
                sh = 26
                is_d = (self.difficulty == i)
                focused = is_focused(dkind)

                if focused:
                    bg_d = 7
                    br_d = dcol
                elif is_d:
                    bg_d = 1
                    br_d = dcol
                else:
                    bg_d = 0
                    br_d = 5

                pyxel.rect(sx, sy, sw, sh, bg_d)
                pyxel.rectb(sx, sy, sw, sh, br_d)
                if focused:
                    fc2 = br_d if blink else 0
                    pyxel.rectb(sx + 1, sy + 1, sw - 2, sh - 2, fc2)

                txt_col = 0 if focused else (dcol if is_d else 5)
                pyxel.text(sx + (sw - len(lbl)*4)//2, sy + 5, lbl, txt_col)

                if is_d and not focused:
                    desc = DIFF_DESC[i]
                    pyxel.text(sx + (sw - len(desc)*4)//2, sy + 17, desc, dcol)
                elif focused:
                    st2 = "SPACE:SET" if not is_d else "SELECTED!"
                    st2_col = br_d if blink else 0
                    pyxel.text(sx + (sw - len(st2)*4)//2, sy + 17, st2, st2_col)

            sby = dy_top + dph + 5
        else:
            sby = dy_top

        # ── ライバル台数選択パネル（レースモード時のみ）──
        if not self.is_time_attack:
            rpw, rph = W - 32, 22
            rpx = 16
            rpy = sby
            rivals_focused = is_focused("rivals")
            rbg = 7 if rivals_focused else 0
            rbr = 10 if rivals_focused else 5
            pyxel.rect(rpx, rpy, rpw, rph, rbg)
            pyxel.rectb(rpx, rpy, rpw, rph, rbr)
            if rivals_focused:
                rfc = rbr if blink else 0
                pyxel.rectb(rpx+1, rpy+1, rpw-2, rph-2, rfc)

            label_col = 0 if rivals_focused else 7
            pyxel.text(rpx + 4, rpy + 3, "RIVALS:", label_col)

            # ◀ 数字 ▶ の形で表示
            nr = getattr(self, 'num_rivals', 3)
            arrow_col = 0 if rivals_focused else 10
            num_str = f"{nr:2d}"
            nx_center = rpx + rpw // 2
            pyxel.text(nx_center - 16, rpy + 3, "< ", arrow_col)
            pyxel.text(nx_center - 4,  rpy + 3, num_str, 0 if rivals_focused else 10)
            pyxel.text(nx_center + 8,  rpy + 3, " >", arrow_col)

            # ヒント
            hint = "" if rivals_focused else f"{nr} car{'s' if nr > 1 else ''}  (1-11)"
            hcol = 0 if rivals_focused else 5
            pyxel.text(rpx + rpw - len(hint)*4 - 4, rpy + 3, hint, hcol)

            sby = rpy + rph + 5
        if self.is_time_attack:
            has_ghost = bool(self.load_ghost()[0])
            gpw, gph = W - 32, 40
            gpx = 16
            gpy = sby
            pyxel.rect(gpx, gpy, gpw, gph, 0)
            pyxel.rectb(gpx, gpy, gpw, gph, 7)
            pyxel.text(gpx + 4, gpy + 3, "GHOST:", 7)

            GHOST_LABELS = ["ON", "OFF"]
            GHOST_KINDS  = ["ghost_on", "ghost_off"]
            GHOST_COLS   = [11, 8]
            gslot_w = (gpw - 8) // 2
            for gi, (glbl, gkind, gcol) in enumerate(zip(GHOST_LABELS, GHOST_KINDS, GHOST_COLS)):
                gsx = gpx + 4 + gi * gslot_w
                gsy = gpy + 14
                gsw = gslot_w - 4
                gsh = 22
                g_active = (self.ghost_enabled == (gi == 0))
                g_focused = is_focused(gkind)
                if g_focused:
                    gbg = 7; gbr = gcol
                elif g_active:
                    gbg = 1; gbr = gcol
                else:
                    gbg = 0; gbr = 5
                pyxel.rect(gsx, gsy, gsw, gsh, gbg)
                pyxel.rectb(gsx, gsy, gsw, gsh, gbr)
                if g_focused:
                    gfc = gbr if blink else 0
                    pyxel.rectb(gsx+1, gsy+1, gsw-2, gsh-2, gfc)
                gtxt_col = 0 if g_focused else (gcol if g_active else 5)
                pyxel.text(gsx + (gsw - len(glbl)*4)//2, gsy + 4, glbl, gtxt_col)
                # ゴーストデータなし表示
                if gi == 0 and not has_ghost:
                    nd = "NO DATA"
                    pyxel.text(gsx + (gsw - len(nd)*4)//2, gsy + 13, nd, 5)
            sby = gpy + gph + 8

        # ── START ボタン ──
        sbw, sbh = 180, 18
        sbx = (W - sbw) // 2
        start_focused = is_focused("start")

        if start_focused:
            bg_s  = 10 if blink else 9
            brd_s = 7
            txt   = ">>> SPACE : START RACE <<<"
            tc    = 0
        else:
            bg_s  = 1
            brd_s = 5
            txt   = "START RACE"
            tc    = 5

        pyxel.rect(sbx, sby, sbw, sbh, bg_s)
        pyxel.rectb(sbx, sby, sbw, sbh, brd_s)
        if start_focused:
            fc3 = brd_s if blink else bg_s
            pyxel.rectb(sbx + 1, sby + 1, sbw - 2, sbh - 2, fc3)
        pyxel.text(sbx + (sbw - len(txt)*4)//2, sby + 5, txt, tc)

        # ── 操作ヒント ──
        pyxel.text(4, H - 10, "WASD: MOVE   SPACE: SELECT   ESC: BACK", 5)

    # ==================================================================

    # ── 道路タイプ定義 (TECHNICAL / SPEEDWAY / OFFROAD と同じパラメータ) ──
    _ROAD_PRESETS = [
        {"label": "NORMAL",  "road_outer": 5, "road_mid": 4, "road_inner": 3,
         "out_distance": 50, "col_outer": 8, "col_mid": 7, "col_inner": 5,
         "col_ground": 11, "night_remap": {11: 21, 5: 1, 7: 13, 8: 2}},
        {"label": "WIDE",    "road_outer": 8, "road_mid": 7, "road_inner": 6,
         "out_distance": 70, "col_outer": 8, "col_mid": 7, "col_inner": 5,
         "col_ground": 11, "night_remap": {11: 21, 5: 1, 7: 13, 8: 2}},
        {"label": "OFFROAD", "road_outer": 3, "road_mid": 2, "road_inner": 1,
         "out_distance": 40, "col_outer": 4, "col_mid": 9, "col_inner": 4,
         "col_ground": 3,  "night_remap": {3: 1, 4: 2, 9: 4}},
    ]
    # 編集モード番号
    _CM_DRAW = 0   # コース点
    _CM_CP   = 1   # チェックポイント
    _CM_GOAL = 2   # ゴールライン
    _CM_WALL = 3   # 壁

    def _maker_reset(self):
        """コースメーカー状態を初期化"""
        self.mk_mode      = self._CM_DRAW
        self.mk_road      = 0
        self.mk_cx        = 128.0
        self.mk_cy        = 96.0
        self.mk_spd       = 1.5
        self.mk_pts       = []
        self.mk_cps       = []
        self.mk_goal      = None
        self.mk_dir       = 0.0
        self.mk_smooth    = []
        self.mk_name_mode = False
        self.mk_name      = ""
        self.mk_msg       = ""
        self.mk_msg_timer = 0
        self.mk_del_idx   = -1
        self.mk_del_timer = 0
        self.mk_walls      = []    # 壁リスト: [{"x1","y1","x2","y2"}, ...]
        self.mk_wall_p1    = None  # 壁の始点 (x,y) or None

    def _maker_msg(self, txt, frames=100):
        self.mk_msg       = txt
        self.mk_msg_timer = frames

    def _maker_refresh_smooth(self):
        if len(self.mk_pts) >= 3:
            self.mk_smooth = self._calc_smooth_points(self.mk_pts)
        else:
            self.mk_smooth = []

    def _maker_build_course(self, name):
        """現在のメーカー状態からコース定義 dict を生成"""
        rp = self._ROAD_PRESETS[self.mk_road]
        pts = self.mk_pts
        # ゴール位置 (未設定なら先頭点)
        gx, gy = self.mk_goal if self.mk_goal else pts[0]
        # チェックポイント (未設定なら等間隔4点を自動生成)
        cps = list(self.mk_cps)
        if not cps:
            n = len(pts)
            cps = [pts[n // 4 % n], pts[n // 2 % n], pts[3 * n // 4 % n], (gx, gy)]
        return {
            "name":           name,
            "control_points": [list(p) for p in pts],
            "checkpoints":    [list(p) for p in cps],
            "start_pos":      [float(gx), float(gy)],
            "start_angle":    self.mk_dir,
            "start_line":     [float(gx), float(gy), float(self.mk_dir),
                               self._ROAD_PRESETS[self.mk_road]["road_outer"]],
            "road_outer":     rp["road_outer"],
            "road_mid":       rp["road_mid"],
            "road_inner":     rp["road_inner"],
            "out_distance":   rp["out_distance"],
            "col_outer":      rp["col_outer"],
            "col_mid":        rp["col_mid"],
            "col_inner":      rp["col_inner"],
            "col_ground":     rp["col_ground"],
            "night_remap":    dict(rp["night_remap"]),
            "walls":          [dict(w) for w in self.mk_walls],
        }

    def _maker_save(self):
        """コースを COURSES に登録してファイル保存"""
        name = self.mk_name.strip().upper()
        if not name:
            self._maker_msg("NAME REQUIRED!")
            return False
        if len(self.mk_pts) < 4:
            self._maker_msg("NEED 4+ POINTS!")
            return False
        cd = self._maker_build_course(name)
        # 同名コースは上書き
        for i, c in enumerate(self.COURSES):
            if c["name"] == name:
                self.COURSES[i] = cd
                sm = self._calc_smooth_points(cd["control_points"])
                rl = self._calc_racing_line(sm, cd["road_outer"])
                self.course_data[i] = {"smooth_points": sm, "racing_line": rl}
                self._save_custom_courses()
                self._maker_msg("OVERWRITTEN!")
                return True
        # 新規追加
        self.COURSES.append(cd)
        sm = self._calc_smooth_points(cd["control_points"])
        rl = self._calc_racing_line(sm, cd["road_outer"])
        self.course_data.append({"smooth_points": sm, "racing_line": rl})
        self._save_custom_courses()
        self._maker_msg("SAVED!")
        return True

    # ── キーコード→文字マッピング ──
    _CM_KEYS = {
        pyxel.KEY_A:"A", pyxel.KEY_B:"B", pyxel.KEY_C:"C", pyxel.KEY_D:"D",
        pyxel.KEY_E:"E", pyxel.KEY_F:"F", pyxel.KEY_G:"G", pyxel.KEY_H:"H",
        pyxel.KEY_I:"I", pyxel.KEY_J:"J", pyxel.KEY_K:"K", pyxel.KEY_L:"L",
        pyxel.KEY_M:"M", pyxel.KEY_N:"N", pyxel.KEY_O:"O", pyxel.KEY_P:"P",
        pyxel.KEY_Q:"Q", pyxel.KEY_R:"R", pyxel.KEY_S:"S", pyxel.KEY_T:"T",
        pyxel.KEY_U:"U", pyxel.KEY_V:"V", pyxel.KEY_W:"W", pyxel.KEY_X:"X",
        pyxel.KEY_Y:"Y", pyxel.KEY_Z:"Z",
        pyxel.KEY_0:"0", pyxel.KEY_1:"1", pyxel.KEY_2:"2", pyxel.KEY_3:"3",
        pyxel.KEY_4:"4", pyxel.KEY_5:"5", pyxel.KEY_6:"6", pyxel.KEY_7:"7",
        pyxel.KEY_8:"8", pyxel.KEY_9:"9", pyxel.KEY_MINUS:"-",
    }

    def _maker_update(self):
        """コースメーカーの毎フレーム処理"""
        if self.mk_msg_timer > 0:
            self.mk_msg_timer -= 1

        # ── 名前入力モード ───────────────────────────────────────────
        if self.mk_name_mode:
            for key, ch in self._CM_KEYS.items():
                if pyxel.btnp(key) and len(self.mk_name) < 12:
                    self.mk_name += ch
                    pyxel.play(1, 1)
            if pyxel.btnp(pyxel.KEY_BACKSPACE) and self.mk_name:
                self.mk_name = self.mk_name[:-1]
            if pyxel.btnp(pyxel.KEY_RETURN):
                if self._maker_save():
                    # 保存成功→コース選択へ戻り、作ったコースを選択
                    self.mk_name_mode = False
                    self.selected_course = len(self.COURSES) - 1
                    # 同名上書きのときは最後とは限らないので名前で探す
                    nm = self.mk_name.strip().upper()
                    for i, c in enumerate(self.COURSES):
                        if c["name"] == nm:
                            self.selected_course = i
                            break
                    self._build_map(self.selected_course)
                    self.best_lap_time = self.best_times.get(self._course_key(), None)
                    self._start_fade(self.STATE_COURSE_SELECT)
                    pyxel.play(1, 2)
            if (pyxel.btnp(pyxel.KEY_ESCAPE) or self._vjoy_esc):
                self.mk_name_mode = False
            return

        # ── 削除確認モード ───────────────────────────────────────────
        if self.mk_del_idx >= 0:
            self.mk_del_timer -= 1
            if self.mk_del_timer <= 0:
                self.mk_del_idx = -1
            if pyxel.btnp(pyxel.KEY_Y):
                self._delete_custom_course(self.mk_del_idx)
                self.mk_del_idx = -1
                self._maker_msg("DELETED!")
                pyxel.play(1, 1)
            if pyxel.btnp(pyxel.KEY_N) or (pyxel.btnp(pyxel.KEY_ESCAPE) or self._vjoy_esc):
                self.mk_del_idx = -1
            return

        # ── カーソル移動 (btn で連続移動) ──────────────────────────
        spd = self.mk_spd
        if pyxel.btn(pyxel.KEY_LEFT)  or pyxel.btn(pyxel.KEY_A): self.mk_cx -= spd
        if pyxel.btn(pyxel.KEY_RIGHT) or pyxel.btn(pyxel.KEY_D): self.mk_cx += spd
        if pyxel.btn(pyxel.KEY_UP)    or pyxel.btn(pyxel.KEY_W): self.mk_cy -= spd
        if pyxel.btn(pyxel.KEY_DOWN)  or pyxel.btn(pyxel.KEY_S): self.mk_cy += spd
        self.mk_cx = max(4.0, min(251.0, self.mk_cx))
        self.mk_cy = max(4.0, min(251.0, self.mk_cy))

        # カーソル速度 (Q/E キー)
        if pyxel.btnp(pyxel.KEY_Q) or self._vjoy_q and self.mk_spd > 0.5: self.mk_spd = round(self.mk_spd - 0.5, 1)
        if pyxel.btnp(pyxel.KEY_E) or self._vjoy_e and self.mk_spd < 5.0: self.mk_spd = round(self.mk_spd + 0.5, 1)

        cx, cy = int(self.mk_cx), int(self.mk_cy)

        # ── M: 編集モード切り替え ─────────────────────────────────
        if pyxel.btnp(pyxel.KEY_M):
            self.mk_mode = (self.mk_mode + 1) % 4
            labels = ["DRAW MODE", "CHECKPOINT MODE", "GOAL MODE", "WALL MODE"]
            self._maker_msg(labels[self.mk_mode], 80)
            if self.mk_mode != self._CM_WALL:
                self.mk_wall_p1 = None
            pyxel.play(1, 1)

        # ── R: 進行方向を回転 (GOALが置かれていれば常に有効) ─────────
        if self.mk_goal is not None:
            step = math.pi / 8   # 22.5度ステップ (16方向)
            if pyxel.btnp(pyxel.KEY_R):
                shift = pyxel.btn(pyxel.KEY_SHIFT)
                self.mk_dir += -step if shift else step
                self.mk_dir %= (2 * math.pi)
                deg = int(round(math.degrees(self.mk_dir))) % 360
                pyxel.play(1, 1)
                self._maker_msg(f"DIR: {deg:3d}deg", 60)

        # ── T: 道路タイプ切り替え ───────────────────────────────────
        if pyxel.btnp(pyxel.KEY_T):
            self.mk_road = (self.mk_road + 1) % len(self._ROAD_PRESETS)
            self._maker_msg(f"ROAD: {self._ROAD_PRESETS[self.mk_road]['label']}", 80)
            pyxel.play(1, 1)

        # ── SPACE: 点を置く ─────────────────────────────────────────
        if pyxel.btnp(pyxel.KEY_SPACE) or self._vjoy_space:
            if self.mk_mode == self._CM_DRAW:
                self.mk_pts.append((cx, cy))
                self._maker_refresh_smooth()
                pyxel.play(1, 1)
            elif self.mk_mode == self._CM_CP:
                self.mk_cps.append((cx, cy))
                self._maker_msg(f"CP {len(self.mk_cps)} SET", 80)
                pyxel.play(1, 1)
            elif self.mk_mode == self._CM_GOAL:
                self.mk_goal = (cx, cy)
                self._maker_msg("GOAL SET", 80)
                pyxel.play(1, 1)
            elif self.mk_mode == self._CM_WALL:
                if self.mk_wall_p1 is None:
                    # 1点目を置く
                    self.mk_wall_p1 = (cx, cy)
                    self._maker_msg("WALL P1 SET - PLACE P2", 120)
                else:
                    # 2点目で壁確定
                    x1, y1 = self.mk_wall_p1
                    self.mk_walls.append({"x1": x1, "y1": y1, "x2": cx, "y2": cy})
                    self.mk_wall_p1 = None
                    self._maker_msg(f"WALL {len(self.mk_walls)} SET", 80)
                pyxel.play(1, 1)

        # ── Z: 直前の点を取り消し ───────────────────────────────────
        if pyxel.btnp(pyxel.KEY_Z):
            if self.mk_mode == self._CM_DRAW and self.mk_pts:
                self.mk_pts.pop()
                self._maker_refresh_smooth()
                pyxel.play(1, 1)
            elif self.mk_mode == self._CM_CP and self.mk_cps:
                self.mk_cps.pop()
                pyxel.play(1, 1)
            elif self.mk_mode == self._CM_GOAL:
                self.mk_goal = None
                pyxel.play(1, 1)
            elif self.mk_mode == self._CM_WALL:
                if self.mk_wall_p1 is not None:
                    self.mk_wall_p1 = None  # 置き中の始点をキャンセル
                elif self.mk_walls:
                    self.mk_walls.pop()
                    self._maker_msg(f"WALL REMOVED", 60)
                pyxel.play(1, 1)

        # ── C: 全点クリア (現在モードのみ) ─────────────────────────
        if pyxel.btnp(pyxel.KEY_C):
            if self.mk_mode == self._CM_DRAW:
                self.mk_pts.clear(); self.mk_smooth.clear()
            elif self.mk_mode == self._CM_CP:
                self.mk_cps.clear()
            elif self.mk_mode == self._CM_GOAL:
                self.mk_goal = None
            elif self.mk_mode == self._CM_WALL:
                self.mk_walls.clear()
                self.mk_wall_p1 = None
            self._maker_msg("CLEARED", 60)
            pyxel.play(1, 1)

        # ── ENTER: コース名入力→保存 ────────────────────────────────
        if pyxel.btnp(pyxel.KEY_RETURN):
            if len(self.mk_pts) < 4:
                self._maker_msg("NEED 4+ POINTS!", 120)
            else:
                self.mk_name_mode = True
                self.mk_name = ""
            pyxel.play(1, 1)

        # ── DEL: カスタムコース削除リスト表示 (選択中が4以降) ──────
        if pyxel.btnp(pyxel.KEY_DELETE):
            # コースメーカー内からは現在のカスタムコース一覧を削除できる
            # 削除したいコースを ←→ で選んで Y/N で確認
            # ここでは「コース選択で選ばれているコース」を削除対象とする
            if self.selected_course >= 4:
                self.mk_del_idx   = self.selected_course
                self.mk_del_timer = 200
                self._maker_msg(f"DELETE '{self.COURSES[self.selected_course]['name']}'? Y/N", 200)
            else:
                self._maker_msg("BUILT-IN COURSE!", 80)
            pyxel.play(1, 1)

        # ── ESC: コース選択へ戻る ───────────────────────────────────
        if (pyxel.btnp(pyxel.KEY_ESCAPE) or self._vjoy_esc):
            self._start_fade(self.STATE_COURSE_SELECT)
            self._build_map(self.selected_course)
            pyxel.play(1, 1)

    # ── マップ座標 ↔ 画面座標 変換定数 ─────────────────────────────
    _MK_MAP_X  = 8
    _MK_MAP_Y  = 8
    _MK_MAP_W  = 176
    _MK_MAP_H  = 176
    _MK_SCALE  = 176 / 256.0   # world(0-255) → screen(0-175)

    def _mk_wx(self, wx): return self._MK_MAP_X + wx * self._MK_SCALE
    def _mk_wy(self, wy): return self._MK_MAP_Y + wy * self._MK_SCALE

    def _maker_draw(self):
        """コースメーカー画面の描画"""
        MX, MY, MW, MH = self._MK_MAP_X, self._MK_MAP_Y, self._MK_MAP_W, self._MK_MAP_H
        SC = self._MK_SCALE
        rp = self._ROAD_PRESETS[self.mk_road]

        # ── 背景 ──
        pyxel.cls(1)

        # マップ領域背景 (地面色)
        pyxel.rect(MX, MY, MW, MH, rp["col_ground"])
        pyxel.rectb(MX - 1, MY - 1, MW + 2, MH + 2, 13)

        # ── スムーズプレビューライン ──
        if len(self.mk_smooth) >= 2:
            for i in range(len(self.mk_smooth)):
                p1 = self.mk_smooth[i]
                p2 = self.mk_smooth[(i + 1) % len(self.mk_smooth)]
                pyxel.line(self._mk_wx(p1[0]), self._mk_wy(p1[1]),
                           self._mk_wx(p2[0]), self._mk_wy(p2[1]), rp["col_mid"])

        # ── 制御点 ──
        for i, (wx, wy) in enumerate(self.mk_pts):
            sx, sy = self._mk_wx(wx), self._mk_wy(wy)
            col = 9 if i == 0 else 8
            pyxel.pset(sx, sy, col)
            if i == 0:
                pyxel.rectb(sx - 2, sy - 2, 5, 5, 9)
            if i % 8 == 0 and i > 0:
                pyxel.text(sx + 1, sy - 4, str(i), 6)

        # ── チェックポイント (黄色 ◆) ──
        for i, (wx, wy) in enumerate(self.mk_cps):
            sx, sy = self._mk_wx(wx), self._mk_wy(wy)
            pyxel.rectb(sx - 2, sy - 2, 5, 5, 10)
            pyxel.pset(sx, sy, 10)

        # ── 壁（灰色の線分） ──
        for w in self.mk_walls:
            sx1 = self._mk_wx(w["x1"]); sy1 = self._mk_wy(w["y1"])
            sx2 = self._mk_wx(w["x2"]); sy2 = self._mk_wy(w["y2"])
            pyxel.line(int(sx1), int(sy1), int(sx2), int(sy2), 13)
            # 端点マーカー
            pyxel.rectb(int(sx1) - 1, int(sy1) - 1, 3, 3, 5)
            pyxel.rectb(int(sx2) - 1, int(sy2) - 1, 3, 3, 13)
        # 壁の置き中プレビュー（始点→カーソル）
        if self.mk_mode == self._CM_WALL and self.mk_wall_p1 is not None:
            sx1 = self._mk_wx(self.mk_wall_p1[0]); sy1 = self._mk_wy(self.mk_wall_p1[1])
            sx2 = self._mk_wx(self.mk_cx);         sy2 = self._mk_wy(self.mk_cy)
            blink_col = 13 if (pyxel.frame_count // 6) % 2 == 0 else 5
            pyxel.line(int(sx1), int(sy1), int(sx2), int(sy2), blink_col)
            pyxel.rectb(int(sx1) - 2, int(sy1) - 2, 5, 5, 13)

        # ── ゴールライン + 進行方向矢印 ──
        if self.mk_goal:
            gsx = self._mk_wx(self.mk_goal[0])
            gsy = self._mk_wy(self.mk_goal[1])

            # --- スタートラインの横棒（進行方向に対して垂直、道幅分） ---
            perp = self.mk_dir + math.pi / 2
            # 道幅に応じた長さ（road_outerをピクセル換算して両側に引く）
            road_half = self._ROAD_PRESETS[self.mk_road]["road_outer"] * 1.0
            # 市松模様のゴールライン（セグメント幅2px）
            seg = 2
            n_segs = max(4, int(road_half * 2 / seg))
            for i in range(-n_segs, n_segs + 1):
                t = i * seg
                # 垂直方向
                bx0 = gsx + math.cos(perp) * t
                by0 = gsy + math.sin(perp) * t
                col_ = 7 if i % 2 == 0 else 0
                # 進行方向に2px幅
                for d in range(3):
                    px_ = bx0 + math.cos(self.mk_dir) * (d - 1)
                    py_ = by0 + math.sin(self.mk_dir) * (d - 1)
                    pyxel.pset(int(px_), int(py_), col_)

            # --- 進行方向矢印 ---
            adx = math.cos(self.mk_dir)
            ady = math.sin(self.mk_dir)
            tip_x = gsx + adx * 12
            tip_y = gsy + ady * 12
            pyxel.line(int(gsx), int(gsy), int(tip_x), int(tip_y), 10)
            head_len = 5; head_wide = 3
            hbx = tip_x - adx * head_len
            hby = tip_y - ady * head_len
            pdx = -ady * head_wide
            pdy =  adx * head_wide
            pyxel.line(int(tip_x), int(tip_y), int(hbx + pdx), int(hby + pdy), 10)
            pyxel.line(int(tip_x), int(tip_y), int(hbx - pdx), int(hby - pdy), 10)

            # --- ゴール中心マーカー ---
            pyxel.rectb(int(gsx) - 2, int(gsy) - 2, 5, 5, 10)

            # --- 方向テキスト ---
            deg = int(round(math.degrees(self.mk_dir))) % 360
            dir_names = {0:"N", 23:"NNE", 45:"NE", 68:"ENE",
                         90:"E", 113:"ESE", 135:"SE", 158:"SSE",
                         180:"S", 203:"SSW", 225:"SW", 248:"WSW",
                         270:"W", 293:"WNW", 315:"NW", 338:"NNW"}
            closest = min(dir_names, key=lambda d: abs((deg - d + 180) % 360 - 180))
            label = dir_names[closest]
            pyxel.text(int(gsx) + 5, int(gsy) - 10, f"{deg}°{label}", 10)

        # ── カーソル (点滅十字) ──
        sx, sy = self._mk_wx(self.mk_cx), self._mk_wy(self.mk_cy)
        cur_cols = [9, 10, 7, 13]   # DRAW=橙, CP=緑, GOAL=白, WALL=灰
        cc = cur_cols[self.mk_mode]
        if (pyxel.frame_count // 8) % 2 == 0:
            pyxel.line(sx - 5, sy, sx + 5, sy, cc)
            pyxel.line(sx, sy - 5, sx, sy + 5, cc)
        else:
            pyxel.pset(sx, sy, cc)

        # ── 右パネル ──
        PX = MX + MW + 6
        PY = MY

        # 編集モード（ハイライト付き）
        mode_labels = ["DRAW ", "CHKPT", "GOAL ", "WALL "]
        mode_cols   = [9, 10, 7, 13]
        for i, (ml, mc) in enumerate(zip(mode_labels, mode_cols)):
            iy = PY + i * 8
            if self.mk_mode == i:
                pyxel.rect(PX - 1, iy - 1, 44, 8, 1)
                pyxel.rectb(PX - 1, iy - 1, 44, 8, mc)
                pyxel.text(PX + 1, iy, f">{ml}", mc)
            else:
                pyxel.text(PX + 1, iy, f" {ml}", 5)

        # 道路タイプ
        rt_cols = [7, 9, 4]
        y = PY + 28
        pyxel.text(PX, y+3,     "ROAD:", 6)
        pyxel.text(PX, y + 11, self._ROAD_PRESETS[self.mk_road]["label"],
                   rt_cols[self.mk_road])

        # 状態表示
        y += 20
        pyxel.text(PX, y,      f"PTS:{len(self.mk_pts):3d}", 7)
        pyxel.text(PX, y + 8,  f"CP :{len(self.mk_cps):3d}", 10)
        goal_str = "SET" if self.mk_goal else "---"
        pyxel.text(PX, y + 16, f"GL :{goal_str}", 7 if self.mk_goal else 5)
        import math as _m
        deg = int(round(_m.degrees(self.mk_dir))) % 360
        pyxel.text(PX, y + 24, f"DIR:{deg:3d}", 10 if self.mk_goal else 5)
        if self.mk_goal:
            pyxel.text(PX, y + 32, "[R]:DIR", 6)
        pyxel.text(PX, y + 40, f"WL :{len(self.mk_walls):3d}", 13)
        pyxel.text(PX, y + 48, f"SPD:{self.mk_spd:.1f}", 6)

        # 操作ヒント
        y += 62
        hints = [
            ("ARROWS", "MOVE"),
            ("SPACE",  "SET PT"),
            ("Z",      "UNDO"),
            ("C",      "CLEAR"),
            ("M",      "MODE"),
            ("T",      "ROAD"),
            ("R",      "DIR+"),
            ("ENTER",  "SAVE"),
            ("DEL",    "DELETE"),
            ("ESC",    "BACK"),
        ]
        for i, (k, v) in enumerate(hints):
            pyxel.text(PX,      y + i * 7, k, 6)
            pyxel.text(PX + 28, y + i * 7, v, 5)

        # ── 削除確認ダイアログ ─────────────────────────────────────
        if self.mk_del_idx >= 0 and self.mk_del_idx < len(self.COURSES):
            cn = self.COURSES[self.mk_del_idx]["name"]
            ddw, ddh = 180, 52
            ddx = (pyxel.width - ddw) // 2
            ddy = (pyxel.height - ddh) // 2
            pyxel.rect(ddx, ddy, ddw, ddh, 0)
            pyxel.rectb(ddx, ddy, ddw, ddh, 8)
            msg = f"DELETE '{cn}'?"
            pyxel.text(ddx + (ddw - len(msg)*4) // 2, ddy + 8, msg, 8)
            pyxel.text(ddx + (ddw - 84)//2, ddy + 20, "This cannot be undone!", 5)
            blink = (pyxel.frame_count // 12) % 2 == 0
            pyxel.text(ddx + 20, ddy + 34, "Y : DELETE", 8 if blink else 7)
            pyxel.text(ddx + 96, ddy + 34, "N / ESC : KEEP", 6)

        # ── 名前入力ダイアログ ──────────────────────────────────────
        if self.mk_name_mode:
            dx, dy, dw, dh = 20, 72, 168, 50
            pyxel.rect(dx, dy, dw, dh, 0)
            pyxel.rectb(dx, dy, dw, dh, 14)
            pyxel.text(dx + 4, dy + 4, "ENTER COURSE NAME:", 14)
            # 入力ボックス
            pyxel.rect(dx + 4, dy + 16, dw - 8, 10, 1)
            pyxel.rectb(dx + 4, dy + 16, dw - 8, 10, 7)
            blink = (pyxel.frame_count // 15) % 2 == 0
            disp = self.mk_name + ("|" if blink else " ")
            pyxel.text(dx + 6, dy + 18, disp, 10)
            pyxel.text(dx + 4, dy + 30, "ENTER:SAVE  ESC:CANCEL", 6)
            # 同名上書き警告
            nm = self.mk_name.strip().upper()
            exists = any(c["name"] == nm for c in self.COURSES)
            if exists and nm:
                pyxel.text(dx + 4, dy + 40, "!OVERWRITE EXISTING!", 8)

        # ── ステータスメッセージ ────────────────────────────────────
        if self.mk_msg_timer > 0:
            mc = 10 if self.mk_msg_timer > 40 else 6
            mw = len(self.mk_msg) * 4
            pyxel.text(MX + (MW - mw) // 2, MY + MH - 10, self.mk_msg, mc)

    def draw_customize_screen(self):
        W, H = pyxel.width, pyxel.height
        pyxel.rect(0, 0, W, H, 0)

        # ── タイトル ──
        pyxel.rect(0, 0, W, 14, 1)
        pyxel.text(W // 2 - 36, 4, "CAR  CUSTOMIZE", 14)

        # ── クレジット表示 ──
        cr_str = f"CR: {self.credits:,}"
        pyxel.text(W - len(cr_str) * 4 - 4, 4, cr_str, 10)

        # ── タブ ──
        tabs = ["COLOR", "ENGINE", "BRAKE", "WEIGHT"]
        tab_w = 60
        tab_start = (W - tab_w * 4) // 2
        for i, label in enumerate(tabs):
            tx = tab_start + i * tab_w
            ty = 16
            is_sel = (self.cust_tab == i)
            bg = 5 if is_sel else 1
            fg = 10 if is_sel else 6
            pyxel.rect(tx, ty, tab_w - 2, 12, bg)
            pyxel.rectb(tx, ty, tab_w - 2, 12, 7 if is_sel else 5)
            pyxel.text(tx + (tab_w - 2 - len(label) * 4) // 2, ty + 3, label, fg)

        # ── タブヒント ──
        pyxel.text(4, 19, "Q/<", 5)
        pyxel.text(W - 20, 19, "E/>", 5)

        content_y = 32

        # ────────────────────────────────────────────────
        # タブ 0: カラー
        # ────────────────────────────────────────────────
        if self.cust_tab == 0:
            owned = self.car_data.get("owned_colors", [0])
            cols_per_row = 4
            swatch_w, swatch_h = 48, 32
            pad = 6
            total_w = cols_per_row * (swatch_w + pad) - pad
            start_x = (W - total_w) // 2

            for i, cd in enumerate(self.CAR_COLORS):
                row = i // cols_per_row
                col = i % cols_per_row
                sx = start_x + col * (swatch_w + pad)
                sy = content_y + row * (swatch_h + 20)

                is_owned   = (i in owned)
                is_sel     = (i == self.cust_color_sel)
                is_equip   = (cd["col"] == self.car_color)

                border_col = 10 if is_sel else (7 if is_equip else 5)
                pyxel.rectb(sx - 1, sy - 1, swatch_w + 2, swatch_h + 2, border_col)
                pyxel.rect(sx, sy, swatch_w, swatch_h, cd["col"])

                # 名前
                name_col = 7 if is_owned else 5
                pyxel.text(sx + (swatch_w - len(cd["name"]) * 4) // 2, sy + swatch_h + 2, cd["name"], name_col)
                # 価格 or OWNED
                if is_equip:
                    pyxel.text(sx + (swatch_w - 24) // 2, sy + swatch_h + 10, "EQUIPPED", 10)
                elif is_owned:
                    pyxel.text(sx + (swatch_w - 20) // 2, sy + swatch_h + 10, "OWNED", 11)
                else:
                    price_str = f"{cd['price']}CR"
                    pyxel.text(sx + (swatch_w - len(price_str) * 4) // 2, sy + swatch_h + 10, price_str, 9)

            # 操作ヒント
            pyxel.text(W // 2 - 72, H - 22, "WASD: SELECT   SPACE: BUY/EQUIP", 6)
            pyxel.text(W // 2 - 40, H - 12, "Q/E: CHANGE TAB", 5)

        # ────────────────────────────────────────────────
        # タブ 1/2/3: アップグレード
        # ────────────────────────────────────────────────
        else:
            key_map   = {1: "engine_lv", 2: "brake_lv", 3: "weight_lv"}
            name_map  = {1: "ENGINE", 2: "BRAKE", 3: "WEIGHT"}
            desc_map  = {
                1: ["ACCEL UP", "TOP SPEED UP", "HANDLING DOWN"],
                2: ["BRAKE POWER UP", "", ""],
                3: ["ACCEL UP", "BRAKE UP", "HANDLING UP"],
            }
            cost_mult = 2000 if self.cust_tab == 3 else 1000
            lv_key    = key_map[self.cust_tab]
            cur_lv    = self.car_data[lv_key]
            next_lv   = cur_lv + 1
            cost      = next_lv * cost_mult if cur_lv < 10 else 0

            # 現在レベル表示
            cx = W // 2
            pyxel.text(cx - 40, content_y, f"{name_map[self.cust_tab]}  LV {cur_lv} / 10", 10 if cur_lv == 10 else 7)

            # レベルバー (10マス)
            bar_x = (W - 102) // 2
            bar_y = content_y + 12
            for b in range(10):
                bx = bar_x + b * 11
                filled = (b < cur_lv)
                col = 10 if filled else 1
                pyxel.rect(bx, bar_y, 9, 8, col)
                pyxel.rectb(bx, bar_y, 9, 8, 7 if filled else 5)

            # コスト
            if cur_lv < 10:
                cost_str = f"NEXT LV{next_lv}: {cost:,} CR"
                can_afford = self.credits >= cost
                cost_col = 10 if can_afford else 8
                pyxel.text(cx - len(cost_str) * 2, bar_y + 14, cost_str, cost_col)
            else:
                pyxel.text(cx - 16, bar_y + 14, "MAX LEVEL!", 9)

            # ── 性能バー ──
            perf = self.get_perf_mult()
            stat_y = bar_y + 28
            stats_def = [
                ("ACCEL",    perf["accel"],    10),
                ("TOP SPEED",perf["max_vel"],   11),
                ("HANDLING", perf["handling"],  14),
                ("BRAKE",    perf["brake"],      9),
            ]
            bar_max_w = 100
            for si, (sname, sval, scol) in enumerate(stats_def):
                sy = stat_y + si * 16
                pyxel.text(4, sy + 1, sname, 6)
                # バー背景
                pyxel.rect(70, sy, bar_max_w, 7, 1)
                # バー（0.6〜1.2 → 0〜100%）
                fill_pct = min((sval - 0.5) / 0.75, 1.0)
                fill_w   = max(2, int(bar_max_w * fill_pct))
                pyxel.rect(70, sy, fill_w, 7, scol)
                pyxel.rectb(70, sy, bar_max_w, 7, 5)
                pct_str = f"{int(sval * 100)}%"
                pyxel.text(174, sy + 1, pct_str, 7)

            # 説明テキスト
            for di, desc in enumerate(desc_map[self.cust_tab]):
                if desc:
                    dcol = 8 if "DOWN" in desc else 11
                    pyxel.text(W // 2 - len(desc) * 2, stat_y + 68 + di * 8, desc, dcol)

            # 操作ヒント
            pyxel.text(W // 2 - 48, H - 22, "SPACE/ENTER: UPGRADE", 6 if cur_lv < 10 else 5)

        # ── メッセージ ──
        if self.cust_msg_timer > 0:
            col = 10 if "EQUIP" in self.cust_msg or "UPGR" in self.cust_msg else 8
            mw  = len(self.cust_msg) * 4
            mx  = (W - mw) // 2
            pyxel.rect(mx - 3, H - 32, mw + 6, 10, 0)
            pyxel.text(mx, H - 30, self.cust_msg, col)

        # ── フッター ──
        pyxel.text(W // 2 - 28, H - 10, "ESC: BACK TO MENU", 5)

    def draw_speedometer(self):
        mx, my = pyxel.width - 30, pyxel.height - 25
        r = 20
        # 背景: 上半円のみ黒で塗りつぶし（スキャンライン方式）
        R_bg = r + 11
        cy_bg = my - 1
        for dy in range(-R_bg, 1):          # dy = -R_bg〜0 (上半分のみ)
            half_w = int(math.sqrt(R_bg * R_bg - dy * dy))
            pyxel.rect(mx - half_w, cy_bg + dy, half_w * 2 + 1, 1, 0)

        rpm_angle_range = max(0, min(int(self.rpm * 180), 180))
        # RPMバー: 各半径×0.5度ステップでpset → 欠落ゼロの確実な塗りつぶし
        r_inner = r + 4
        r_outer = r + 9
        steps = rpm_angle_range * 2          # 0.5度ステップ
        for i_half in range(0, steps + 1):
            i = i_half / 2.0
            rad = math.radians(180.0 + i)
            cos_r = math.cos(rad)
            sin_r = math.sin(rad)
            col = 8 if i > 150 else (10 if i > 110 else 11)
            for rr in range(r_inner, r_outer + 1):
                pyxel.pset(round(mx + cos_r * rr),
                           round(my - 1 + sin_r * rr), col)

        pyxel.circ(mx, my, r + 2, 0)
        pyxel.circ(mx, my, r, 5)

        for a in range(135, 406, 45):
            rad = math.radians(a)
            pyxel.line(mx + math.cos(rad)*(r-3), my + math.sin(rad)*(r-3),
                       mx + math.cos(rad)*r, my + math.sin(rad)*r, 7)

        angle = 135 + (self.velocity / 0.6) * 270
        rad = math.radians(angle)
        pyxel.line(mx, my, mx + math.cos(rad)*(r-2), my + math.sin(rad)*(r-2), 8)

        pyxel.circ(mx, my, 2, 7)
        pyxel.text(mx - 15, my + 5, f"{self.kilometer:3}km/h", 7)

        is_redzone = self.rpm > 0.85
        show_gear = not is_redzone or (pyxel.frame_count % 6 < 3)
        pyxel.rect(mx - 4, my - 15, 9, 9, 0)

        if show_gear:
            if self.is_reverse:
                pyxel.text(mx - 2, my - 13, "R", 8)
            else:
                gear_col = 8 if is_redzone else (10 if self.rpm > 0.7 else 7)
                pyxel.text(mx - 2, my - 13, f"{self.gear + 1}", gear_col)

        if is_redzone and (pyxel.frame_count % 10 < 5):
            if self.gear != 4:
                pyxel.text(mx - 18, my - 22, "SHIFT UP!", 8)

        bx, by = pyxel.width - 60, 20
        col = 7 if self.is_night_mode else 0
        pyxel.text(bx, by, "BEST LAP:", col)
        if self.best_lap_time is not None:
            pyxel.text(bx + 10, by + 10, f"{self.best_lap_time:.2f}s", 10)
        else:
            pyxel.text(bx + 10, by + 10, "---.--s", 5)

        # ハンコン接続中インジケーター
        if _HAS_JOY:
            pyxel.text(4, pyxel.height - 18, "WHEEL", 11)

        # ── ハンドルスライダー（画面下部中央）──
        si      = getattr(self, 'steer_input', 0.0)
        W       = pyxel.width
        H       = pyxel.height
        bar_half = 40          # 中央から左右それぞれ40px
        bar_y   = H - 8
        cx_bar  = W // 2

        # 背景バー
        pyxel.rect(cx_bar - bar_half - 1, bar_y - 1, bar_half * 2 + 2, 5, 0)
        # 左右の目盛り線
        pyxel.line(cx_bar - bar_half, bar_y - 1, cx_bar - bar_half, bar_y + 3, 5)
        pyxel.line(cx_bar,            bar_y - 1, cx_bar,            bar_y + 3, 5)
        pyxel.line(cx_bar + bar_half, bar_y - 1, cx_bar + bar_half, bar_y + 3, 5)
        # 入力量バー（中央から伸びる）
        fill_len = int(abs(si) * bar_half)
        if fill_len > 0:
            bar_col = 10 if abs(si) < 0.6 else 8   # 普通は緑、強ハンドルは赤
            if si < 0:
                pyxel.rect(cx_bar - fill_len, bar_y, fill_len, 3, bar_col)
            else:
                pyxel.rect(cx_bar, bar_y, fill_len, 3, bar_col)
        # センターマーカー（常時表示）
        pyxel.rect(cx_bar - 1, bar_y - 1, 3, 5, 7)
        # インジケーター（現在位置のノブ）
        knob_x = int(cx_bar + si * bar_half)
        pyxel.rect(knob_x - 2, bar_y - 2, 5, 7, 7)
        pyxel.rect(knob_x - 1, bar_y - 1, 3, 5, 10 if abs(si) > 0.25 else 11)


App()