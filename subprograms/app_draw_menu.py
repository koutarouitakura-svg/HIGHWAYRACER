from .common import *


class AppDrawMenuMixin:
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

