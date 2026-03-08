from .common import pyxel, math, random, json, os, sys, base64, IS_WEB, _ask_open, _ask_save, _HAS_JOY, _pg, _joy_axis, _joy_btn, _joy_hat, SUPABASE_URL, SUPABASE_ANON_KEY
try:
    import js # type: ignore
except ImportError:
    js = None
from .player_progression import PlayerProgressionMixin

class AppDrawMixin(PlayerProgressionMixin):
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
                box_h = 128 if not self.is_time_attack else 65
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

                    xp_panel_y = total_y + 22
                    if self.prize_anim_phase >= 3 and (self.xp_anim_total_gain > 0 or self.xp_anim_active or self.session_xp_awarded):
                        disp_gain = self.xp_anim_display_gain if self.xp_anim_active else self.xp_anim_total_gain
                        cur_lv = self.xp_anim_current_level if self.xp_anim_active else self.player_level
                        cur_xp = self.xp_anim_current_xp if self.xp_anim_active else self.player_xp
                        req_xp = self.get_required_xp_for_level(cur_lv)
                        bar_x = x_txt
                        bar_w = len(s) * 4
                        pyxel.text(bar_x, xp_panel_y, f"+{disp_gain} XP", 12 if disp_gain > 0 else 5)
                        pyxel.text(bar_x + bar_w - 24, xp_panel_y, f"LV{cur_lv}", 10)
                        pyxel.rect(bar_x, xp_panel_y+10, bar_w, 7, 1)
                        pyxel.rectb(bar_x, xp_panel_y+10, bar_w, 7, 5)
                        fill_w = (bar_w - 2) if cur_lv >= self.MAX_PLAYER_LEVEL else int((cur_xp / max(1, req_xp)) * (bar_w - 2))
                        if fill_w > 0:
                            pyxel.rect(bar_x + 1, xp_panel_y + 11, fill_w, 5, 11 if not self.xp_anim_active else 10)
                        xp_text = "MAX" if cur_lv >= self.MAX_PLAYER_LEVEL else f"{cur_xp}/{req_xp}"
                        pyxel.text(bar_x + (bar_w - len(xp_text) * 4) // 2, xp_panel_y + 20, xp_text, 7)

                    pyxel.text(x_txt + 7, pyxel.height / 2 + 8 + 68, "PUSH 'R' TO MENU", 6)

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
                elif self.is_time_attack:
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

            pyxel.rect(0, 0, W, 14, 1)
            pyxel.text(W // 2 - 20, 4, "OPTIONS", 10)

            panel_w, panel_h = 210, 138
            px = (W - panel_w) // 2
            py = 22

            pyxel.rect(px, py, panel_w, panel_h, 0)
            pyxel.rectb(px, py, panel_w, panel_h, 7)

            at_mt = "AT (AUTO)" if self.is_automatic else "MT (MANUAL)"
            quality_labels = {1: "ULTRA", 2: "HIGH", 3: "MEDIUM", 4: "LOW"}
            quality_lbl = quality_labels.get(self.map_pixel_size, "HIGH")
            sens = getattr(self, 'wheel_sensitivity', 5)
            sens_lbl = f"{sens:2d} / 10"

            player_name = getattr(self, 'player_name', 'PLAYER')
            if getattr(self, 'player_name_editing', False):
                shown_name = getattr(self, 'player_name_input', player_name)
                if (pyxel.frame_count // 15) % 2 == 0 and len(shown_name) < 12:
                    shown_name += "_"
                name_lbl = f"PLAYER NAME:  {shown_name}"
            else:
                name_lbl = f"PLAYER NAME:  {player_name}"

            opt_items = [
                (f"TRANSMISSION: {at_mt}", 10),
                (f"GRAPHICS:     {quality_lbl}", 11),
                (f"WHEEL SENS:   {sens_lbl}", 12),
                (name_lbl, 7),
                ("CONTROLS", 6),
                ("BACK", 6),
            ]
            item_h = 18
            for i, (label, col) in enumerate(opt_items):
                iy = py + 8 + i * item_h
                if i == self.opt_focus:
                    pyxel.rect(px + 6, iy - 2, panel_w - 12, item_h - 1, 1)
                    pyxel.rectb(px + 6, iy - 2, panel_w - 12, item_h - 1, 10)
                    if (pyxel.frame_count // 8) % 2 == 0:
                        pyxel.text(px + 10, iy + 4, ">", 10)
                    col_draw = 10
                else:
                    col_draw = col
                pyxel.text(px + 20, iy + 4, label[:29], col_draw)

            if self.opt_focus == 1:
                bar_y = py + 8 + 1 * item_h + item_h - 2
                bar_x = px + 20
                dot_w = 12
                for d in range(4):
                    dx = bar_x + 72 + d * (dot_w + 2)
                    filled = (d < self.map_pixel_size)
                    pyxel.rect(dx, bar_y + 1, dot_w, 6, 11 if filled else 1)
                    pyxel.rectb(dx, bar_y + 1, dot_w, 6, 11 if filled else 5)

            if self.opt_focus == 2:
                bar_y = py + 8 + 2 * item_h + item_h - 2
                bar_x = px + 20
                dot_w = 14
                for d in range(10):
                    dx = bar_x + d * (dot_w + 1)
                    filled = (d < sens)
                    col_d = 12 if filled else 1
                    pyxel.rect(dx, bar_y + 1, dot_w, 6, col_d)
                    pyxel.rectb(dx, bar_y + 1, dot_w, 6, 12 if filled else 5)

            if self.opt_focus == 4:
                ow, oh = 220, 84
                ox = (W - ow) // 2
                oy = (H - oh) // 2 + 28
                pyxel.rect(ox, oy, ow, oh, 0)
                pyxel.rectb(ox, oy, ow, oh, 11)
                pyxel.text(ox + (ow - 56) // 2, oy + 5, "--- CONTROLS ---", 11)
                lines = [
                    ("WHEEL",        "STEER",         6, 7),
                    ("ACCEL PEDAL",  "ACCELERATE",    6, 7),
                    ("BRAKE PEDAL",  "BRAKE",         6, 7),
                    ("RIGHT PADDLE", "SHIFT UP",      6, 7),
                    ("LEFT PADDLE",  "SHIFT DOWN",    6, 7),
                    ("OPTIONS",      "PAUSE / BACK",  6, 7),
                ]
                for li, (key, desc, kc, dc) in enumerate(lines):
                    lx = ox + 8
                    ly = oy + 18 + li * 10
                    pyxel.text(lx,      ly, key,  kc)
                    pyxel.text(lx + 92, ly, desc, dc)

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
            req_xp = self.get_required_xp_for_level()
            xp_disp = "MAX" if self.player_level >= self.MAX_PLAYER_LEVEL else f"{self.player_xp} / {req_xp}"
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

            player_level = self.stats.get("player_level", 0)
            player_xp = self.stats.get("player_xp", 0)
            max_level = getattr(self, "MAX_PLAYER_LEVEL", 50)
            if player_level >= max_level:
                xp_str = "MAX"
            else:
                xp_str = f"{player_xp} / {self.get_required_xp_for_level(player_level)}"

            rows = [
                ("PLAYER LEVEL",    f"LV {player_level}"),
                ("CURRENT EXP",     xp_str),
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

            # [E] MAKER ボタン（LV50で解放）
            player_level = self.stats.get("player_level", 0)
            maker_unlocked = player_level >= getattr(self, "MAX_PLAYER_LEVEL", 50)
            pyxel.rect(rx - 2, ry + 36, 60, 20, 1)
            pyxel.rectb(rx - 2, ry + 36, 60, 20, 14 if maker_unlocked else 5)
            pyxel.text(rx, ry + 39, "[E] MAKER", 14 if maker_unlocked else 5)
            if maker_unlocked:
                pyxel.text(rx, ry + 47, "UNLOCKED", 11)
            else:
                pyxel.text(rx, ry + 47, f"LV {getattr(self, 'MAX_PLAYER_LEVEL', 50)}", 8)

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
            pyxel.rect(rx - 2, ry + 64, 60, 34, 0)
            pyxel.rectb(rx - 2, ry + 64, 60, 34, 5)
            pyxel.text(rx, ry + 67, "SHARE:", 5)
            pyxel.text(rx, ry + 75, "[X] EXPORT", 6)
            pyxel.text(rx, ry + 83, "[I] IMPORT", 6)
            if self.is_time_attack:
                pyxel.text(rx, ry + 91, "[G]ghost", 9)
                pyxel.text(rx + 32, ry + 91, "[L]load", 9)

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
                    player_level = self.stats.get("player_level", 0)
                    pyxel.text(8, content_y-28, f"PLAYER LV {player_level}", 11)
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
                player_level = self.stats.get("player_level", 0)
                desc_map  = {
                    1: ["ACCEL UP", "TOP SPEED UP", "HANDLING DOWN"],
                    2: ["BRAKE POWER UP", "", ""],
                    3: ["ACCEL UP", "BRAKE UP", "HANDLING UP"],
                }
                cost_mult = 2000 if self.cust_tab == 3 else 1000
                lv_key    = key_map[self.cust_tab]
                cur_lv    = self.car_data[lv_key]
                next_lv   = cur_lv + 1
                req_player_lv = max(0, (next_lv - 1) * 3)
                cost      = next_lv * cost_mult if cur_lv < 10 else 0

                # 現在レベル表示
                cx = W // 2
                pyxel.text(cx - 40, content_y, f"{name_map[self.cust_tab]}  LV {cur_lv} / 10", 10 if cur_lv == 10 else 7)
                pyxel.text(8, content_y-28, f"PLAYER LV {player_level}", 11)

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
                    can_level = player_level >= req_player_lv
                    cost_col = 10 if (can_afford and can_level) else 8
                    pyxel.text(cx - len(cost_str) * 2, bar_y + 14, cost_str, cost_col)
                    req_str = f"REQ PLAYER LV {req_player_lv}"
                    req_col = 11 if can_level else 8
                    pyxel.text(cx - len(req_str) * 2, bar_y + 22, req_str, req_col)
                else:
                    pyxel.text(cx - 16, bar_y + 14, "MAX LEVEL!", 9)

                # ── 性能バー ──
                perf = self.get_perf_mult()
                stat_y = bar_y + 36
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
                hint_col = 6 if (cur_lv < 10 and player_level >= req_player_lv) else 5
                pyxel.text(W // 2 - 48, H - 22, "SPACE/ENTER: UPGRADE", hint_col)

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

