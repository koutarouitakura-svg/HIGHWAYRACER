from .common import pyxel


class AppUpdateMenuMixin:
    def _update_state_name_entry(self):
        allowed_keys = [
            (pyxel.KEY_A,'A'),(pyxel.KEY_B,'B'),(pyxel.KEY_C,'C'),(pyxel.KEY_D,'D'),
            (pyxel.KEY_E,'E'),(pyxel.KEY_F,'F'),(pyxel.KEY_G,'G'),(pyxel.KEY_H,'H'),
            (pyxel.KEY_I,'I'),(pyxel.KEY_J,'J'),(pyxel.KEY_K,'K'),(pyxel.KEY_L,'L'),
            (pyxel.KEY_M,'M'),(pyxel.KEY_N,'N'),(pyxel.KEY_O,'O'),(pyxel.KEY_P,'P'),
            (pyxel.KEY_Q,'Q'),(pyxel.KEY_R,'R'),(pyxel.KEY_S,'S'),(pyxel.KEY_T,'T'),
            (pyxel.KEY_U,'U'),(pyxel.KEY_V,'V'),(pyxel.KEY_W,'W'),(pyxel.KEY_X,'X'),
            (pyxel.KEY_Y,'Y'),(pyxel.KEY_Z,'Z'),
            (pyxel.KEY_0,'0'),(pyxel.KEY_1,'1'),(pyxel.KEY_2,'2'),(pyxel.KEY_3,'3'),
            (pyxel.KEY_4,'4'),(pyxel.KEY_5,'5'),(pyxel.KEY_6,'6'),(pyxel.KEY_7,'7'),
            (pyxel.KEY_8,'8'),(pyxel.KEY_9,'9'),(pyxel.KEY_MINUS,'-'),(pyxel.KEY_UNDERSCORE,'_'),
        ]
        if pyxel.btnp(pyxel.KEY_BACKSPACE) and self.player_name_input:
            self.player_name_input = self.player_name_input[:-1]; pyxel.play(1, 1)
        elif pyxel.btnp(pyxel.KEY_RETURN) or pyxel.btnp(pyxel.KEY_SPACE) or self._vjoy_space:
            name = self.player_name_input.strip()[:12]
            if name:
                self.player_name = name
                self.online_my_name = name
                self.save_options()
                self.state = self.STATE_TITLE
                pyxel.play(1, 2)
            else:
                pyxel.play(1, 4)
        else:
            for key, ch in allowed_keys:
                if pyxel.btnp(key) and len(self.player_name_input) < 12:
                    self.player_name_input += ch; pyxel.play(1, 1)

    def _update_state_title(self):
        if pyxel.btnp(pyxel.KEY_SPACE) or self._vjoy_space:
            self._start_fade(self.STATE_MENU)
            pyxel.play(1, 2)
        if (pyxel.btnp(pyxel.KEY_ESCAPE) or self._vjoy_esc):
            pyxel.quit()

    def _update_state_menu(self):
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

    def _update_state_options(self):
        import string as _str

        OPT_ITEMS = 6   # TRANSMISSION, MAP DETAIL, WHEEL SENS, PLAYER NAME, CONTROLS, BACK

        # ── プレイヤーネーム編集中 ─────────────────────────────
        if getattr(self, "player_name_editing", False):
            if pyxel.btnp(pyxel.KEY_ESCAPE) or self._vjoy_esc:
                self.player_name_editing = False
                self.player_name_input = self.player_name
                pyxel.play(1, 1)

            elif pyxel.btnp(pyxel.KEY_BACKSPACE) and self.player_name_input:
                self.player_name_input = self.player_name_input[:-1]
                pyxel.play(1, 1)

            elif pyxel.btnp(pyxel.KEY_RETURN):
                new_name = self.player_name_input.strip()[:12]
                self.player_name = new_name if new_name else "PLAYER"
                self.player_name_input = self.player_name
                self.player_name_editing = False
                self.save_options()
                pyxel.play(1, 2)

            else:
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
                    (pyxel.KEY_8,'8'),(pyxel.KEY_9,'9'),
                    (pyxel.KEY_MINUS,'-'),(pyxel.KEY_UNDERSCORE,'_'),
                ]:
                    if pyxel.btnp(key) and len(self.player_name_input) < 12:
                        self.player_name_input += ch
                        pyxel.play(1, 1)

        # ── 通常のオプション操作 ────────────────────────────────
        else:
            up   = pyxel.btnp(pyxel.KEY_UP) or pyxel.btnp(pyxel.KEY_W) or self._vjoy_up
            down = pyxel.btnp(pyxel.KEY_DOWN) or pyxel.btnp(pyxel.KEY_S) or self._vjoy_dn
            if up:
                self.opt_focus = (self.opt_focus - 1) % OPT_ITEMS
                pyxel.play(1, 1)
            if down:
                self.opt_focus = (self.opt_focus + 1) % OPT_ITEMS
                pyxel.play(1, 1)

            if pyxel.btnp(pyxel.KEY_SPACE) or pyxel.btnp(pyxel.KEY_RETURN) or self._vjoy_space:
                pyxel.play(1, 1)
                if self.opt_focus == 0:
                    self.is_automatic = not self.is_automatic
                elif self.opt_focus == 1:
                    pass  # MAP DETAIL は左右で操作
                elif self.opt_focus == 2:
                    pass  # WHEEL SENS は左右で操作
                elif self.opt_focus == 3:
                    self.player_name_editing = True
                    self.player_name_input = getattr(self, "player_name", "PLAYER")
                elif self.opt_focus == 4:
                    pass  # CONTROLS はインフォ表示のみ
                elif self.opt_focus == 5:
                    self.save_options()
                    self._start_fade(self.STATE_MENU)

            lr_left  = pyxel.btnp(pyxel.KEY_LEFT) or pyxel.btnp(pyxel.KEY_A) or self._vjoy_left
            lr_right = pyxel.btnp(pyxel.KEY_RIGHT) or pyxel.btnp(pyxel.KEY_D) or self._vjoy_right

            # MAP DETAIL: 左右で map_pixel_size を 1〜4 で調整
            if self.opt_focus == 1:
                if lr_left:
                    old = self.map_pixel_size
                    self.map_pixel_size = max(1, self.map_pixel_size - 1)
                    if self.map_pixel_size != old:
                        self._build_map(self.selected_course)
                        pyxel.play(1, 1)
                if lr_right:
                    old = self.map_pixel_size
                    self.map_pixel_size = min(4, self.map_pixel_size + 1)
                    if self.map_pixel_size != old:
                        self._build_map(self.selected_course)
                        pyxel.play(1, 1)

            # WHEEL SENS: 左右で 1〜10 で調整
            if self.opt_focus == 2:
                if lr_left:
                    self.wheel_sensitivity = max(1, self.wheel_sensitivity - 1)
                    pyxel.play(1, 1)
                if lr_right:
                    self.wheel_sensitivity = min(10, self.wheel_sensitivity + 1)
                    pyxel.play(1, 1)

            if pyxel.btnp(pyxel.KEY_ESCAPE) or self._vjoy_esc:
                self.save_options()
                self._start_fade(self.STATE_MENU)
                pyxel.play(1, 1)

    def _update_state_mode_select(self):
        if pyxel.btnp(pyxel.KEY_LEFT) or pyxel.btnp(pyxel.KEY_A) or self._vjoy_left or \
           pyxel.btnp(pyxel.KEY_RIGHT) or pyxel.btnp(pyxel.KEY_D) or self._vjoy_right:
            self.is_time_attack = not self.is_time_attack; pyxel.play(1, 1)
        if pyxel.btnp(pyxel.KEY_SPACE) or self._vjoy_space:
            self._start_fade(self.STATE_COURSE_SELECT); pyxel.play(1, 2)
        if (pyxel.btnp(pyxel.KEY_ESCAPE) or self._vjoy_esc):
            self._start_fade(self.STATE_MENU); pyxel.play(1, 1)

    def _update_state_course_select(self):
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

    def _update_state_time_select(self):
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

    def _update_state_course_maker(self):
        self._maker_update()

    def _update_state_status(self):
        if (pyxel.btnp(pyxel.KEY_ESCAPE) or self._vjoy_esc): self._start_fade(self.STATE_MENU); pyxel.play(1, 1)

    def _update_state_ranking(self):
        if (pyxel.btnp(pyxel.KEY_ESCAPE) or self._vjoy_esc): self._start_fade(self.STATE_COURSE_SELECT); pyxel.play(1, 1)

