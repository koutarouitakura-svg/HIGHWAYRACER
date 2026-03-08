from .common import pyxel, random, _time
from .online import OnlineClient


class AppUpdateOnlineMixin:
    def _update_state_online_entry(self):
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
                        self.online_my_name = self.player_name or self.online_my_name or self.online_my_id
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
                    self.online_my_name = self.player_name or self.online_my_name or self.online_my_id
                    self.online_client   = OnlineClient(
                        "", self.online_room_id, self.online_my_id)
                    self.online_status   = "Connecting..."
                    self._start_fade(self.STATE_ONLINE_LOBBY); pyxel.play(1, 2)

            if (pyxel.btnp(pyxel.KEY_ESCAPE) or self._vjoy_esc):
                self.online_join_input  = ""
                self.online_join_active = False
                self._start_fade(self.STATE_MENU); pyxel.play(1, 1)

    def _update_state_online_lobby(self):
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
                                                  "angle": 0, "vel": 0,
                                                  "name": msg.get("player_name", pid[:4].upper())}
                        print(f"[LOBBY] peer追加: {pid}, 合計: {len(self.online_peers)+1}人")
                    # join受信したら自分もjoinを返す（相互認識）
                    self.online_client.send_priority({
                        "type": "join",
                        "player_id": self.online_my_id,
                        "player_name": self.online_my_name,
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
                        "player_name": self.online_my_name,
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

