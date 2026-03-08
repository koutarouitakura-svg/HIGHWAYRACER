from .common import pyxel, math, random, _HAS_JOY


class AppDrawCoreMixin:
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

