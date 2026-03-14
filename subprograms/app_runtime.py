from .common import pyxel, math, random, json, os, sys, base64, IS_WEB, _ask_open, _ask_save, _HAS_JOY, _pg, _joy_axis, _joy_btn, _joy_hat, SUPABASE_URL, SUPABASE_ANON_KEY
from .online import OnlineClient, PeerInterpolator
from .rival import RivalCar
from .player_progression import PlayerProgressionMixin
from pathlib import Path
import shutil
try:
    import js # type: ignore
except ImportError:
    js = None
class AppRuntimeMixin(PlayerProgressionMixin):
        def _project_root_dir(self):
            if getattr(sys, "frozen", False):
                return Path(sys.executable).resolve().parent
            return Path(__file__).resolve().parent.parent

        def _bundle_root_dir(self):
            if hasattr(sys, "_MEIPASS"):
                return Path(sys._MEIPASS)
            return Path(__file__).resolve().parent.parent

        def _asset_path(self, filename):
            candidates = [
                self.assets_dir / filename,
                self._project_root_dir() / "assets" / filename,
                self._bundle_root_dir() / "assets" / filename,
                self._bundle_root_dir() / "subprograms" / filename,
                self._bundle_root_dir() / filename,
                Path(__file__).resolve().parent / filename,
            ]
            for path in candidates:
                if path.exists():
                    return str(path)
            raise FileNotFoundError(
                f"Asset not found: {filename} | searched: "
                + " / ".join(str(p) for p in candidates)
            )

        def _ensure_runtime_dirs(self):
            self.assets_dir.mkdir(parents=True, exist_ok=True)
            self.saves_dir.mkdir(parents=True, exist_ok=True)

        def _has_any_save_json(self):
            return any(self.saves_dir.glob("*.json"))

        def _is_debug_player(self):
            return str(getattr(self, "player_name", "")).upper() == "KATORA09"

        def _initial_credit_bonus(self):
            return self.DEBUG_INITIAL_CREDITS if self._is_debug_player() else 0

        def _migrate_legacy_runtime_files(self):
            legacy_json_names = [
                "best_times.json",
                "custom_courses.json",
                "credits.json",
                "stats.json",
                "options.json",
                "car_data.json",
            ]
            for name in legacy_json_names:
                legacy_path = self._project_root_dir() / name
                target_path = self.saves_dir / name
                if legacy_path.exists() and not target_path.exists():
                    shutil.copy2(legacy_path, target_path)

            if getattr(sys, "frozen", False):
                return

            legacy_png_dir = Path(__file__).resolve().parent
            for legacy_path in legacy_png_dir.glob("*.png"):
                target_path = self.assets_dir / legacy_path.name
                if not target_path.exists():
                    shutil.copy2(legacy_path, target_path)

        def __init__(self):
            # 実行ファイルの場所（ベースディレクトリ）を取得
            # Pyxelのapp2exeを使用した場合、sys.executable に exeのパス が入る
            exe_name = os.path.basename(sys.executable).lower()
            base_dir = self._project_root_dir()
            self.assets_dir = base_dir / "assets"
            self.saves_dir = base_dir / "saves"
            self._ensure_runtime_dirs()
            first_launch = not self._has_any_save_json()
            self._migrate_legacy_runtime_files()

            # ベースディレクトリを元にファイルの絶対パスを作成
            self.save_file = os.path.join(self.saves_dir, "best_times.json")
            self.custom_courses_file = os.path.join(self.saves_dir, "custom_courses.json")
            self.credits_file  = os.path.join(self.saves_dir, "credits.json")
            self.stats_file    = os.path.join(self.saves_dir, "stats.json")
            self.options_file  = os.path.join(self.saves_dir, "options.json")
            self.car_data_file = os.path.join(self.saves_dir, "car_data.json")
            self.online_client  = None
            self.online_peers   = {}             # pid -> 補間済み描画用状態(dict)
            self._peer_interp   = {}             # pid -> PeerInterpolator インスタンス
            self.online_room_id = ""
            self.online_my_id   = ""
            self.online_my_name = ""
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
            self.STATE_NAME_ENTRY    = 14

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
            self.is_grand_prix   = False
            self.selected_course = 0
            self.selected_cup    = 0
            self.difficulty      = 1   # 0=初級(EASY), 1=中級(NORMAL), 2=上級(HARD)
            self.mode_select_focus = 0
            self.time_sel_focus  = 0   # 0=DAY, 1=NIGHT, 2=EASY, 3=NORMAL, 4=HARD, 5=START
            self.ghost_enabled   = True   # ゴースト表示ON/OFF
            self.ghost_data      = []     # 保存済みゴーストフレーム（再生用）
            self.ghost_frame_idx = 0      # 再生位置（実フレーム数）
            self.ghost_sample    = 1      # ゴーストのサンプリングレート
            self.ghost_record    = []     # 今走行中の録画バッファ
            self._share_msg       = ""    # エクスポート/インポート結果フィードバック
            self._share_msg_timer = 0
            self.player_name      = ""
            self.player_name_input = ""
            self.cloud_img_bank   = 2
            self.cloud_img_u      = 0
            self.cloud_img_v      = 128
            self.cloud_img_w      = 50
            self.cloud_img_h      = 50

            pyxel.init(256, 192, title="Highway Racer", quit_key=pyxel.KEY_NONE)

            self.setup_sounds()
            self.setup_custom_palette()
            pyxel.images[0].load(0, 0, self._asset_path("car.png"))
            pyxel.images[2].load(0, 0, self._asset_path("title.png"))
            pyxel.images[2].load(0, 32, self._asset_path("rock.png"))
            pyxel.images[self.cloud_img_bank].load(
                self.cloud_img_u, self.cloud_img_v, self._asset_path("cloud.png")
            )

            # カスタムコースをファイルから読み込み COURSES に追加
            self._load_custom_courses()

            for course_def in self.COURSES:
                self._normalize_course_definition(course_def)

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
            self.load_options()   # map_pixel_size, player_name などを復元
            self.credits  = self.load_credits()
            self.stats    = self.load_stats()
            self._ensure_grand_prix_results()
            self._reset_grand_prix_state()
            self._ensure_player_progression()
            self.car_data = self.load_car_data()
            self.player_name_input = self.player_name
            if first_launch:
                self.player_name = ""
                self.player_name_input = ""
                self.player_name_editing = True
                self.state = self.STATE_NAME_ENTRY
            elif not self.player_name:
                self.state = self.STATE_NAME_ENTRY
            self.online_my_name = self.player_name
            # カスタマイズ画面の選択状態
            self.cust_tab      = 0   # 0=カラー, 1=エンジン, 2=ブレーキ, 3=軽量化
            self.cust_color_sel = 0  # 選択中のカラーインデックス
            self.cust_msg      = ""
            self.cust_msg_timer = 0
            self.reset()
            self._maker_reset()

            pyxel.run(self.update, self.draw)

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
                self.clouds.append({
                    "x": random.uniform(0, pyxel.width),
                    "y": random.uniform(5, 40),
                    "depth": random.uniform(0.1, 0.8),
                    "img": self.cloud_img_bank,
                    "u": self.cloud_img_u,
                    "v": self.cloud_img_v,
                    "orig_w": self.cloud_img_w,
                    "orig_h": self.cloud_img_h,
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
            self._reset_goal_xp_animation_state()
            self._reset_grand_prix_result_animation()

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

        def _start_fade(self, target_state):
            """指定ステートへのフェードアウト開始"""
            self.fade_target = target_state
            self.fade_dir    = 1
            self.fade_alpha  = 0

        def _ensure_grand_prix_results(self):
            results = self.stats.setdefault("grand_prix_results", {})
            for cup in self.GRAND_PRIX_CUPS:
                results.setdefault(cup["name"], {})
            return results

        def _grand_prix_points_for_rank(self, rank):
            table = [5, 3, 2, 1]
            idx = rank - 1
            if 0 <= idx < len(table):
                return table[idx]
            return 0

        def _grand_prix_forced_night_mode(self, cup_idx=None):
            idx = self.selected_cup if cup_idx is None else int(cup_idx)
            cup = self.GRAND_PRIX_CUPS[idx % len(self.GRAND_PRIX_CUPS)]
            return cup["name"] == "TOURING CUP"

        def _apply_grand_prix_fixed_settings(self, cup_idx=None):
            self.difficulty = 1
            self.num_rivals = 3
            self.is_night_mode = self._grand_prix_forced_night_mode(cup_idx)

        def _reset_grand_prix_state(self):
            self.grand_prix_active = False
            self.grand_prix_cup_index = 0
            self.grand_prix_race_index = 0
            self.grand_prix_total_points = []
            self.grand_prix_previous_points = []
            self.grand_prix_race_points = []
            self.grand_prix_result_order = []
            self.grand_prix_final_order = []
            self.grand_prix_final_rank = 0
            self.grand_prix_final_prize = 0
            self.grand_prix_pending_course = None
            self.grand_prix_last_points_awarded = False
            self.grand_prix_result_complete = False
            self.grand_prix_last_finish_positions = []

        def _reset_grand_prix_result_animation(self):
            count = self.num_rivals + 1
            self.grand_prix_anim_phase = 0
            self.grand_prix_anim_timer = 0
            self.grand_prix_display_race_points = [0.0] * count
            self.grand_prix_display_total_points = [0.0] * count
            self.grand_prix_result_complete = False

        def _grand_prix_driver_labels(self):
            total = self.num_rivals + 1
            player_label = (getattr(self, "player_name", "") or "PLAYER")[:12]
            return [player_label] + [f"RIVAL {i}" for i in range(1, total)]

        def _grand_prix_current_cup(self):
            cup_idx = getattr(self, "grand_prix_cup_index", self.selected_cup)
            return self.GRAND_PRIX_CUPS[cup_idx % len(self.GRAND_PRIX_CUPS)]

        def _prepare_grand_prix_for_start(self):
            cup_idx = self.selected_cup % len(self.GRAND_PRIX_CUPS)
            cup = self.GRAND_PRIX_CUPS[cup_idx]
            self._apply_grand_prix_fixed_settings(cup_idx)
            total = self.num_rivals + 1
            self.grand_prix_active = True
            self.grand_prix_cup_index = cup_idx
            self.grand_prix_race_index = 0
            self.grand_prix_total_points = [0] * total
            self.grand_prix_previous_points = [0] * total
            self.grand_prix_race_points = [0] * total
            self.grand_prix_result_order = list(range(total))
            self.grand_prix_final_order = []
            self.grand_prix_final_rank = 0
            self.grand_prix_final_prize = 0
            self.grand_prix_pending_course = cup["courses"][0]
            self.grand_prix_last_points_awarded = False
            self.grand_prix_last_finish_positions = [999] * total
            self._reset_grand_prix_result_animation()

        def _prime_grand_prix_race(self):
            if not (self.is_grand_prix and getattr(self, "grand_prix_active", False)):
                return
            cup = self._grand_prix_current_cup()
            self._apply_grand_prix_fixed_settings(self.grand_prix_cup_index)
            race_idx = max(0, min(self.grand_prix_race_index, len(cup["courses"]) - 1))
            self.selected_course = cup["courses"][race_idx]
            self.grand_prix_pending_course = self.selected_course
            self._build_map(self.selected_course)
            self.best_lap_time = self.best_times.get(self._course_key(), None)

        def _grand_prix_is_final_race(self):
            cup = self._grand_prix_current_cup()
            return self.grand_prix_race_index >= len(cup["courses"]) - 1

        def _grand_prix_overall_order(self):
            totals = list(getattr(self, "grand_prix_total_points", []))
            final_ranks = list(getattr(self, "grand_prix_last_finish_positions", []))
            order = list(range(len(totals)))
            order.sort(key=lambda idx: (-totals[idx], final_ranks[idx] if idx < len(final_ranks) else 999, idx))
            return order

        def _grand_prix_base_prize_for_rank(self, rank):
            total_cars = self.num_rivals + 1
            if total_cars <= 1:
                rank_prize = 1000
            else:
                t = (rank - 1) / max(total_cars - 1, 1)
                rank_prize = int(1000 * (1 - t) + 50 * t)
            prize_diff_mult = [0.7, 1.0, 1.5][self.difficulty]
            return int(rank_prize * self.goal_laps * prize_diff_mult)

        def _save_grand_prix_cup_result(self):
            cup = self._grand_prix_current_cup()
            results = self._ensure_grand_prix_results()
            entry = results.setdefault(cup["name"], {})
            last_rank = int(self.grand_prix_final_rank)
            last_points = int(self.grand_prix_total_points[0]) if self.grand_prix_total_points else 0
            entry.update(
                {
                    "last_rank": last_rank,
                    "last_points": last_points,
                    "best_rank": min(int(entry.get("best_rank", last_rank or 99)), last_rank or 99),
                    "best_points": max(int(entry.get("best_points", 0)), last_points),
                    "play_count": int(entry.get("play_count", 0)) + 1,
                    "prize": int(self.grand_prix_final_prize),
                }
            )
            self.save_stats()

        def _grand_prix_finish_race(self):
            total = self.num_rivals + 1
            self.grand_prix_previous_points = list(self.grand_prix_total_points)
            finish_order = [(0, self.car_progress)]
            for idx, rival in enumerate(self.rivals, start=1):
                finish_order.append((idx, rival.progress))
            finish_order.sort(key=lambda entry: entry[1], reverse=True)
            race_points = [0] * total
            finish_positions = [999] * total
            for rank, (driver_idx, _) in enumerate(finish_order, start=1):
                finish_positions[driver_idx] = rank
                race_points[driver_idx] = self._grand_prix_points_for_rank(rank)
                if driver_idx == 0:
                    self.goal_rank = rank
            self.grand_prix_race_points = race_points
            self.grand_prix_last_finish_positions = finish_positions
            self.grand_prix_total_points = [
                prev + gain for prev, gain in zip(self.grand_prix_previous_points, race_points)
            ]
            self.grand_prix_result_order = list(range(total))
            self.grand_prix_result_order.sort(
                key=lambda idx: (-race_points[idx], -self.grand_prix_total_points[idx], idx)
            )
            self._reset_grand_prix_result_animation()
            self.grand_prix_anim_phase = 1
            self.grand_prix_last_points_awarded = True

            if self._grand_prix_is_final_race():
                self.grand_prix_final_order = self._grand_prix_overall_order()
                self.grand_prix_final_rank = self.grand_prix_final_order.index(0) + 1
                self.goal_rank = self.grand_prix_final_rank
                self.grand_prix_final_prize = int(self._grand_prix_base_prize_for_rank(self.grand_prix_final_rank) * 10 / 3)
                self.prize_amount = self.grand_prix_final_prize
                self.prize_bonus = 0
                self.prize_display = 0
                self.prize_anim_timer = 0
                self.prize_anim_phase = 0
                self._save_grand_prix_cup_result()
            else:
                self.grand_prix_final_order = []
                self.grand_prix_final_rank = 0
                self.grand_prix_final_prize = 0
                self.prize_amount = 0
                self.prize_bonus = 0
                self.prize_display = 0
                self.prize_anim_timer = 0
                self.prize_anim_phase = 0

        def _update_grand_prix_result_animation(self):
            if not getattr(self, "grand_prix_last_points_awarded", False):
                return
            if self.grand_prix_anim_phase == 0:
                return

            self.grand_prix_anim_timer += 1
            if self.grand_prix_anim_phase == 1:
                progress = min(self.grand_prix_anim_timer / 24.0, 1.0)
                eased = 1.0 - (1.0 - progress) * (1.0 - progress)
                self.grand_prix_display_race_points = [
                    gain * eased for gain in self.grand_prix_race_points
                ]
                self.grand_prix_display_total_points = list(self.grand_prix_previous_points)
                if progress >= 1.0:
                    self.grand_prix_anim_phase = 2
                    self.grand_prix_anim_timer = 0
            elif self.grand_prix_anim_phase == 2:
                progress = min(self.grand_prix_anim_timer / 36.0, 1.0)
                eased = 1.0 - (1.0 - progress) * (1.0 - progress)
                self.grand_prix_display_race_points = list(self.grand_prix_race_points)
                self.grand_prix_display_total_points = [
                    prev + (total - prev) * eased
                    for prev, total in zip(self.grand_prix_previous_points, self.grand_prix_total_points)
                ]
                if progress >= 1.0:
                    self.grand_prix_display_total_points = list(self.grand_prix_total_points)
                    self.grand_prix_anim_phase = 3
                    self.grand_prix_anim_timer = 0
            elif self.grand_prix_anim_phase == 3:
                if self._grand_prix_is_final_race():
                    self.prize_anim_phase = 1
                    self.grand_prix_anim_phase = 4
                    self.grand_prix_anim_timer = 0
                else:
                    self.grand_prix_result_complete = True
                    self.grand_prix_anim_phase = 4
            elif self.grand_prix_anim_phase == 4:
                if self._grand_prix_is_final_race():
                    if self.prize_anim_phase == 1:
                        self.prize_anim_timer += 1
                        progress = min(self.prize_anim_timer / 60.0, 1.0)
                        self.prize_display = int(self.prize_amount * progress)
                        if self.prize_anim_timer >= 65:
                            self.prize_display = self.prize_amount
                            self.prize_anim_phase = 3
                            self.credits += self.prize_amount
                            self.stats["total_credits"] += self.prize_amount
                            self.save_credits()
                            self.save_stats()
                    if self.prize_anim_phase >= 3:
                        self._start_goal_xp_animation_if_needed()
                        self._update_goal_xp_animation()
                        if not getattr(self, 'xp_anim_active', False) and getattr(self, 'pending_goal_xp', 0) <= 0:
                            self.grand_prix_result_complete = True
                else:
                    self.grand_prix_result_complete = True

        def _continue_grand_prix_from_results(self):
            if self._grand_prix_is_final_race():
                cup = self._grand_prix_current_cup()
                self._reset_grand_prix_state()
                self.selected_course = cup["courses"][0]
                self._build_map(self.selected_course)
                self.best_lap_time = self.best_times.get(self._course_key(), None)
                self._start_fade(self.STATE_MENU)
                return

            self.grand_prix_race_index += 1
            self._prime_grand_prix_race()
            self.reset()
            self._start_fade(self.STATE_PLAY)
