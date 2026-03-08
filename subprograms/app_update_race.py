from .common import pyxel, math, random, _time, _HAS_JOY, _pg, _joy_axis, _joy_btn, _joy_hat
from .online import PeerInterpolator


class AppUpdateRaceMixin:
    def _update_state_pause(self):
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

    def _update_state_customize(self):
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

    def _update_state_play(self):
        # 性能乗数をフレーム先頭で1回だけ計算してキャッシュ
        self._perf_cache = self.get_perf_mult()
        if self.online_client and self.online_client.connected:
            self.online_client.send({
                "type":      "pos",
                "player_id": self.online_my_id,
                "player_name": self.online_my_name,
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
                    if "player_name" in msg:
                        self.online_peers.setdefault(pid, {})["name"] = msg.get("player_name") or pid[:4].upper()
                    self._peer_interp[pid].push(msg, now_t)

                elif mtype == "goal" and pid and pid != self.online_my_id:
                    # 相手のゴールを記録
                    if not hasattr(self, 'online_finish_order'):
                        self.online_finish_order = []
                    if pid not in [e[0] for e in self.online_finish_order]:
                        self.online_finish_order.append((pid, msg.get("player_name", self.online_peers.get(pid, {}).get("name", pid[:4].upper()))))

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
                                "player_name": self.online_my_name,
                                "finish_time": getattr(self, 'total_race_time', 0),
                            })
                            # ゴール順位リストに自分を追加
                            if not hasattr(self, 'online_finish_order'):
                                self.online_finish_order = []
                            if self.online_my_id not in [e[0] for e in self.online_finish_order]:
                                self.online_finish_order.append((self.online_my_id, self.online_my_name or "YOU"))
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

    def update_effects(self):
        for c in self.clouds:
            c["x"] += self.velocity * c["speed_factor"] * 10
            if c["x"] < -100: c["x"] = pyxel.width + 100
            if c["x"] > pyxel.width + 100: c["x"] = -100

