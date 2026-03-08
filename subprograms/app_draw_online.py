from .common import *


class AppDrawOnlineMixin:
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

