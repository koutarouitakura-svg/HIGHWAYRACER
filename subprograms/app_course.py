from .common import pyxel, math, random, json, os, sys, base64, IS_WEB, _ask_open, _ask_save, _HAS_JOY, _pg, _joy_axis, _joy_btn, _joy_hat, SUPABASE_URL, SUPABASE_ANON_KEY
try:
    import js # type: ignore
except ImportError:
    js = None
class AppCourseMixin:
        def _course_key(self, idx=None):
            """ベストタイム保存用キー (コース名ベース, 削除でズレない)"""
            i = self.selected_course if idx is None else idx
            return f"best_lap_{self.COURSES[i]['name']}"

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

