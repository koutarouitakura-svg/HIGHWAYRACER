from .common import pyxel

class PlayerProgressionMixin:
    MAX_PLAYER_LEVEL = 50
    CLEAR_XP_REWARD = 100

    def get_required_xp_for_level(self, level=None):
        lv = self.player_level if level is None else int(level)
        if lv >= self.MAX_PLAYER_LEVEL:
            return 0
        return 100 + lv * 20

    def _ensure_player_progression(self):
        if not hasattr(self, 'stats') or self.stats is None:
            self.stats = {}
        self.stats.setdefault('player_level', 0)
        self.stats.setdefault('player_xp', 0)
        self.player_level = max(0, min(int(self.stats.get('player_level', 0)), self.MAX_PLAYER_LEVEL))
        self.player_xp = max(0, int(self.stats.get('player_xp', 0)))
        self.stats['player_level'] = self.player_level
        self.stats['player_xp'] = self.player_xp
        return self.player_level, self.player_xp

    def _sync_player_progression_to_stats(self):
        self.stats['player_level'] = int(self.player_level)
        self.stats['player_xp'] = int(self.player_xp)

    def _calc_distance_xp(self, distance=None):
        dist = self.session_distance if distance is None else distance
        return max(0, int(dist)) * 0.1

    def _simulate_xp_gain(self, start_level, start_xp, amount):
        level = int(start_level)
        xp = int(start_xp)
        remaining = max(0, int(amount))
        while remaining > 0 and level < self.MAX_PLAYER_LEVEL:
            req = self.get_required_xp_for_level(level)
            take = min(req - xp, remaining)
            xp += take
            remaining -= take
            if xp >= req:
                level += 1
                xp = 0
        if level >= self.MAX_PLAYER_LEVEL:
            level = self.MAX_PLAYER_LEVEL
            xp = 0
        return level, xp

    def _apply_xp_gain(self, amount):
        self._ensure_player_progression()
        gain = max(0, int(amount))
        if gain <= 0:
            return self.player_level, self.player_xp, self.player_level, self.player_xp
        start_level, start_xp = self.player_level, self.player_xp
        end_level, end_xp = self._simulate_xp_gain(start_level, start_xp, gain)
        self.player_level, self.player_xp = end_level, end_xp
        self._sync_player_progression_to_stats()
        self.save_stats()
        return start_level, start_xp, end_level, end_xp

    def _reset_goal_xp_animation_state(self):
        self.session_xp_awarded = False
        self.pending_goal_xp = 0
        self.xp_anim_active = False
        self.xp_anim_total_gain = 0
        self.xp_anim_display_gain = 0
        self.xp_anim_start_level = getattr(self, 'player_level', 0)
        self.xp_anim_start_xp = getattr(self, 'player_xp', 0)
        self.xp_anim_current_level = getattr(self, 'player_level', 0)
        self.xp_anim_current_xp = getattr(self, 'player_xp', 0)
        self.xp_anim_target_level = getattr(self, 'player_level', 0)
        self.xp_anim_target_xp = getattr(self, 'player_xp', 0)
        self.xp_anim_wait = 18
        self.xp_anim_level_sound_cooldown = 0

    def _queue_goal_xp_award(self):
        if getattr(self, 'session_xp_awarded', False):
            return 0
        gain = self.CLEAR_XP_REWARD + self._calc_distance_xp()
        self.pending_goal_xp = gain
        return gain

    def _start_goal_xp_animation_if_needed(self):
        if getattr(self, 'xp_anim_active', False):
            return
        gain = int(getattr(self, 'pending_goal_xp', 0))
        if gain <= 0:
            return
        self._ensure_player_progression()
        start_level, start_xp = self.player_level, self.player_xp
        end_level, end_xp = self._simulate_xp_gain(start_level, start_xp, gain)
        self._apply_xp_gain(gain)
        self.pending_goal_xp = 0
        self.session_xp_awarded = True
        self.xp_anim_active = True
        self.xp_anim_total_gain = gain
        self.xp_anim_display_gain = 0
        self.xp_anim_start_level = start_level
        self.xp_anim_start_xp = start_xp
        self.xp_anim_current_level = start_level
        self.xp_anim_current_xp = start_xp
        self.xp_anim_target_level = end_level
        self.xp_anim_target_xp = end_xp
        self.xp_anim_wait = 18
        self.xp_anim_level_sound_cooldown = 0

    def _update_goal_xp_animation(self):
        if not getattr(self, 'xp_anim_active', False):
            return
        if self.xp_anim_wait > 0:
            self.xp_anim_wait -= 1
            return
        if self.xp_anim_level_sound_cooldown > 0:
            self.xp_anim_level_sound_cooldown -= 1
        remaining = self.xp_anim_total_gain - self.xp_anim_display_gain
        if remaining <= 0:
            self.xp_anim_active = False
            self.xp_anim_current_level = self.xp_anim_target_level
            self.xp_anim_current_xp = self.xp_anim_target_xp
            return
        step = max(1, min(remaining, max(2, self.xp_anim_total_gain // 50)))
        prev_level = self.xp_anim_current_level
        self.xp_anim_display_gain += step
        cur_level, cur_xp = self._simulate_xp_gain(self.xp_anim_start_level, self.xp_anim_start_xp, self.xp_anim_display_gain)
        self.xp_anim_current_level = cur_level
        self.xp_anim_current_xp = cur_xp
        if cur_level > prev_level and self.xp_anim_level_sound_cooldown == 0:
            try:
                pyxel.play(3, 5)
            except Exception:
                pass
            self.xp_anim_level_sound_cooldown = 8

    def _grant_session_distance_xp_now(self):
        if getattr(self, 'session_xp_awarded', False):
            return 0
        gain = self._calc_distance_xp()
        if gain > 0:
            self._apply_xp_gain(gain)
        self.session_xp_awarded = True
        return gain
