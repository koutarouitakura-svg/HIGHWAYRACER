from .common import pyxel, math, random, json, os, sys, base64, IS_WEB, _ask_open, _ask_save, _HAS_JOY, _pg, _joy_axis, _joy_btn, _joy_hat, SUPABASE_URL, SUPABASE_ANON_KEY
try:
    import js # type: ignore
except ImportError:
    js = None
class AppStorageMixin:
        def load_best_times(self):
            if IS_WEB:
                try:
                    data = js.window.localStorage.getItem("highway_racer_best_times")
                    if data:
                        return json.loads(data)
                except Exception:
                    pass
                return {}
            else:
                if os.path.exists(self.save_file):
                    try:
                        with open(self.save_file, "r") as f:
                            return json.load(f)
                    except Exception:
                        pass
                return {}

        def save_best_times(self):
            if IS_WEB:
                try:
                    js.window.localStorage.setItem("highway_racer_best_times", json.dumps(self.best_times))
                except Exception:
                    pass
            else:
                try:
                    with open(self.save_file, "w") as f:
                        json.dump(self.best_times, f)
                except Exception:
                    pass

        def _ghost_file_path(self):
            name = self.COURSES[self.selected_course]["name"].replace(" ", "_")
            return os.path.join(os.path.dirname(self.save_file), f"ghost_{name}.json")

        def save_ghost(self, frames):
            """ベストラップのゴーストデータを保存。
            毎フレームデータをそのまま保存（最大6000フレーム≒200秒分）。
            サイズが大きすぎる場合のみ間引く。"""
            SAMPLE = 1  # 原則1フレームごと保存
            # 6000フレーム超なら間引く（異常に長いラップへの安全弁）
            if len(frames) > 6000:
                SAMPLE = 2
            sampled = frames[::SAMPLE]
            data = {"frames": sampled, "sample": SAMPLE}
            if IS_WEB:
                try:
                    key = f"highway_racer_ghost_{self.COURSES[self.selected_course]['name']}"
                    js.window.localStorage.setItem(key, json.dumps(data))
                except Exception:
                    pass
            else:
                try:
                    with open(self._ghost_file_path(), "w") as f:
                        json.dump(data, f)
                except Exception:
                    pass

        def load_ghost(self):
            """ゴーストデータを読み込む。{"frames":[...],"sample":N} 形式、または旧形式リストを返す。
            戻り値: (frames_list, sample_rate) のタプル。データなしは ([], 1)。"""
            raw = None
            if IS_WEB:
                try:
                    key = f"highway_racer_ghost_{self.COURSES[self.selected_course]['name']}"
                    data = js.window.localStorage.getItem(key)
                    if data:
                        raw = json.loads(data)
                except Exception:
                    pass
            else:
                path = self._ghost_file_path()
                if os.path.exists(path):
                    try:
                        with open(path, "r") as f:
                            raw = json.load(f)
                    except Exception:
                        pass
            if raw is None:
                return [], 1
            # 新形式: dict with "frames" key
            if isinstance(raw, dict) and "frames" in raw:
                return raw["frames"], int(raw.get("sample", 1))
            # 旧形式: list（5フレームサンプリング済み）
            if isinstance(raw, list):
                return raw, 5
            return [], 1

        def _online_broadcast_settings(self):
            """ホストが現在の設定をルーム全員に送信する。"""
            if self.online_client and self.online_client.connected:
                self.online_client.send_priority({
                    "type":       "settings",
                    "player_id":  self.online_my_id,
                    "course_idx": self.selected_course,
                    "night":      self.is_night_mode,
                    "laps":       self.goal_laps,
                    "course_name": self.COURSES[self.selected_course]["name"],
                })

        def _set_share_msg(self, msg, frames=150):
            self._share_msg = msg
            self._share_msg_timer = frames

        def _make_share_html(self, json_str, title, hint_lines):
            """データをBase64埋め込みのHTMLに変換して返す。
            ブラウザで開けばJSONの表示・コピー・ダウンロードができる。
            OS問わず（Windows / Mac / Linux）どのブラウザでも動く。"""
            b64 = base64.b64encode(json_str.encode("utf-8")).decode()
            hint_html = "".join(f"<li>{h}</li>" for h in hint_lines)
            fname = title.replace(" ", "_") + ".json"
            return f"""<!DOCTYPE html>
    <html lang="ja"><head><meta charset="UTF-8">
    <title>Highway Racer &#8211; {title}</title>
    <style>
      body{{margin:0;background:#111;color:#eee;font-family:monospace;padding:24px}}
      h2{{color:#fd0;margin:0 0 8px}}
      ul{{color:#aaa;font-size:13px;margin:4px 0 16px;padding-left:20px}}
      textarea{{display:block;width:100%;box-sizing:border-box;height:260px;
               background:#1a1a1a;color:#4f4;border:1px solid #444;
               padding:8px;font-size:11px;resize:vertical}}
      .btns{{margin:10px 0}}
      button{{padding:8px 20px;margin-right:8px;background:#222;color:#eee;
             border:1px solid #666;cursor:pointer;font-size:14px;border-radius:4px}}
      button:hover{{background:#444}}
      #msg{{color:#fd0;font-size:13px;margin-top:6px;min-height:18px}}
    </style></head><body>
    <h2>&#127947; Highway Racer &mdash; {title}</h2>
    <ul>{hint_html}</ul>
    <textarea id="ta" readonly></textarea>
    <div class="btns">
      <button onclick="copy()">&#128203; JSONをコピー</button>
      <button onclick="dl()">&#128190; .jsonとして保存</button>
    </div>
    <div id="msg"></div>
    <script>
    const data = atob("{b64}");
    document.getElementById("ta").value = data;
    function copy(){{
      navigator.clipboard.writeText(data).then(
        ()=>{{document.getElementById("msg").textContent="コピーしました！"}},
        ()=>{{document.getElementById("ta").select();document.execCommand("copy");
             document.getElementById("msg").textContent="コピーしました（フォールバック）"}}
      );
    }}
    function dl(){{
      const a=document.createElement("a");
      a.href="data:application/json;charset=utf-8,"+encodeURIComponent(data);
      a.download="{fname}";a.click();
    }}
    </script></body></html>"""

        def export_ghost(self):
            """現在コースのゴーストをJSON + HTMLファイルに書き出す。"""
            if IS_WEB:
                self._set_share_msg("WEB版ではエクスポート非対応"); return
            frames, sample = self.load_ghost()
            if not frames:
                self._set_share_msg("ゴーストデータがありません"); return
            cd = self.COURSES[self.selected_course]
            payload = json.dumps({
                "type": "ghost", "version": 1,
                "course": cd["name"], "sample": sample, "frames": frames,
            }, separators=(',', ':'))
            default = f"ghost_{cd['name'].replace(' ','_')}.json"
            path = _ask_save("ゴーストを保存", default,
                             (("JSON files", "*.json"), ("All files", "*.*")))
            if not path:
                self._set_share_msg("キャンセルしました", 60); return
            try:
                with open(path, "w", encoding="utf-8") as f: f.write(payload)
                # 同フォルダにHTMLも出力
                html_path = os.path.splitext(path)[0] + ".html"
                hint = [
                    "このHTMLをブラウザで開くとJSONの確認・ダウンロードができます",
                    "受け取った .json を相手の claude.py と同じフォルダに置き",
                    "コース選択画面でタイムアタックモードにして [L] キーでインポート",
                ]
                html = self._make_share_html(payload, f"Ghost – {cd['name']}", hint)
                with open(html_path, "w", encoding="utf-8") as f: f.write(html)
                self._set_share_msg(f"エクスポート完了: {os.path.basename(path)}")
            except Exception as e:
                self._set_share_msg(f"エクスポート失敗: {e}")

        def import_ghost(self):
            """JSONファイルから他人のゴーストを読み込み、現在コースに上書きする。"""
            if IS_WEB:
                self._set_share_msg("WEB版ではインポート非対応"); return
            path = _ask_open("ゴーストを開く",
                             (("JSON files", "*.json"), ("All files", "*.*")))
            if not path:
                self._set_share_msg("キャンセルしました", 60); return
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if data.get("type") != "ghost":
                    self._set_share_msg("ゴーストファイルではありません"); return
                cd = self.COURSES[self.selected_course]
                if data.get("course") != cd["name"]:
                    self._set_share_msg(f"コース不一致: {data.get('course','')}"); return
                save_data = {"frames": data["frames"], "sample": data.get("sample", 1)}
                with open(self._ghost_file_path(), "w", encoding="utf-8") as f:
                    json.dump(save_data, f)
                self.ghost_data, self.ghost_sample = self.load_ghost()
                self._set_share_msg("ゴーストをインポートしました！")
            except Exception as e:
                self._set_share_msg(f"インポート失敗: {e}")

        def export_course(self):
            """選択中コースをJSON + HTMLに書き出す。"""
            if IS_WEB:
                self._set_share_msg("WEB版ではエクスポート非対応"); return
            cd = self.COURSES[self.selected_course]
            # tuple → list に変換してJSONシリアライズ可能にする
            export_cd = dict(cd)
            export_cd["control_points"] = [list(p) for p in cd["control_points"]]
            export_cd["checkpoints"]    = [list(p) for p in cd["checkpoints"]]
            export_cd["start_pos"]      = list(cd["start_pos"])
            export_cd["walls"]          = cd.get("walls", [])
            payload = json.dumps({
                "type": "course", "version": 1, "course": export_cd,
            }, separators=(',', ':'), ensure_ascii=False)
            default = f"course_{cd['name'].replace(' ','_')}.json"
            path = _ask_save("コースを保存", default,
                             (("JSON files", "*.json"), ("All files", "*.*")))
            if not path:
                self._set_share_msg("キャンセルしました", 60); return
            try:
                with open(path, "w", encoding="utf-8") as f: f.write(payload)
                html_path = os.path.splitext(path)[0] + ".html"
                hint = [
                    "このHTMLをブラウザで開くとJSONの確認・ダウンロードができます",
                    "受け取った .json を claude.py と同じフォルダに置いて",
                    "コース選択画面で [I] キーを押してインポート",
                ]
                html = self._make_share_html(payload, f"Course – {cd['name']}", hint)
                with open(html_path, "w", encoding="utf-8") as f: f.write(html)
                self._set_share_msg(f"エクスポート完了: {os.path.basename(path)}")
            except Exception as e:
                self._set_share_msg(f"エクスポート失敗: {e}")

        def import_course(self):
            """JSONファイルからコースを読み込んでカスタムコースとして追加する。"""
            if IS_WEB:
                self._set_share_msg("WEB版ではインポート非対応"); return
            path = _ask_open("コースを開く",
                             (("JSON files", "*.json"), ("All files", "*.*")))
            if not path:
                self._set_share_msg("キャンセルしました", 60); return
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if data.get("type") != "course":
                    self._set_share_msg("コースファイルではありません"); return
                cd_raw = data["course"]
                if "night_remap" in cd_raw:
                    cd_raw["night_remap"] = {int(k): v for k, v in cd_raw["night_remap"].items()}
                cd_raw["control_points"] = [tuple(p) for p in cd_raw["control_points"]]
                cd_raw["checkpoints"]    = [tuple(p) for p in cd_raw["checkpoints"]]
                cd_raw["start_pos"]      = tuple(cd_raw["start_pos"])
                cd_raw["start_angle"]    = float(cd_raw.get("start_angle", 0.0))
                cd_raw["start_line"]     = list(cd_raw["start_line"])
                cd_raw["walls"]          = cd_raw.get("walls", [])
                existing = {c["name"] for c in self.COURSES}
                if cd_raw["name"] in existing:
                    self._set_share_msg(f"既に存在: {cd_raw['name']}"); return
                self.COURSES.append(cd_raw)
                smooth = self._calc_smooth_points(cd_raw["control_points"])
                rl     = self._calc_racing_line(smooth, cd_raw["road_outer"])
                self.course_data.append({"smooth_points": smooth, "racing_line": rl})
                self._save_custom_courses()
                self.selected_course = len(self.COURSES) - 1
                self._build_map(self.selected_course)
                self._set_share_msg(f"インポート完了: {cd_raw['name']}")
            except Exception as e:
                self._set_share_msg(f"インポート失敗: {e}")

        def _ta_ranking_key(self, idx=None):
            i = self.selected_course if idx is None else idx
            return f"ta_ranking_{self.COURSES[i]['name']}"

        def get_ta_ranking(self, idx=None):
            """コースのタイムアタックランキング上位5件リストを返す"""
            return self.best_times.get(self._ta_ranking_key(idx), [])

        def add_ta_record(self, lap_time):
            """タイムアタック記録を追加し上位5件を保持。新記録ならTrue返す"""
            key = self._ta_ranking_key()
            ranking = self.best_times.get(key, [])
            old_best = ranking[0] if ranking else None
            ranking.append(lap_time)
            ranking.sort()
            ranking = ranking[:5]
            self.best_times[key] = ranking
            self.best_lap_time = ranking[0]
            self.best_times[self._course_key()] = ranking[0]
            self.save_best_times()
            return (old_best is None or lap_time < old_best)

        def load_credits(self):
            if IS_WEB:
                try:
                    data = js.window.localStorage.getItem("highway_racer_credits")
                    if data:
                        return int(json.loads(data)) + self.DEBUG_INITIAL_CREDITS
                except Exception:
                    pass
                return self.DEBUG_INITIAL_CREDITS
            else:
                if os.path.exists(self.credits_file):
                    try:
                        with open(self.credits_file, "r") as f:
                            return int(json.load(f)) + self.DEBUG_INITIAL_CREDITS
                    except Exception:
                        pass
                return self.DEBUG_INITIAL_CREDITS

        def save_credits(self):
            if IS_WEB:
                try:
                    js.window.localStorage.setItem("highway_racer_credits", json.dumps(self.credits))
                except Exception:
                    pass
            else:
                try:
                    with open(self.credits_file, "w") as f:
                        json.dump(self.credits, f)
                except Exception:
                    pass

        def load_stats(self):
            default = {
                "race_count":      0,   # レース参加回数
                "first_count":     0,   # 1位になった回数
                "total_credits":   0,   # 総獲得クレジット（使用前の累計）
                "total_distance":  0.0, # 総走行距離（ワールド単位）
                "total_frames":    0,   # 総走行フレーム数（30fps換算で秒数計算）
                "player_level":    0,
                "player_xp":       0,
            }
            if IS_WEB:
                try:
                    data = js.window.localStorage.getItem("highway_racer_stats")
                    if data:
                        loaded = json.loads(data)
                        default.update(loaded)
                except Exception:
                    pass
            else:
                if os.path.exists(self.stats_file):
                    try:
                        with open(self.stats_file, "r") as f:
                            loaded = json.load(f)
                            default.update(loaded)
                    except Exception:
                        pass
            return default

        def save_stats(self):
            if IS_WEB:
                try:
                    js.window.localStorage.setItem("highway_racer_stats", json.dumps(self.stats))
                except Exception:
                    pass
            else:
                try:
                    with open(self.stats_file, "w") as f:
                        json.dump(self.stats, f)
                except Exception:
                    pass

        def load_options(self):
            """map_pixel_size / wheel_sensitivity / player_name をロードする"""
            default = {
                "map_pixel_size": 2,
                "wheel_sensitivity": 5,
                "player_name": "PLAYER",
            }
            if IS_WEB:
                try:
                   data = js.window.localStorage.getItem("highway_racer_options")
                   if data:
                        default.update(json.loads(data))
                except Exception:
                    pass
            else:
                if os.path.exists(self.options_file):
                    try:
                        with open(self.options_file, "r") as f:
                            default.update(json.load(f))
                    except Exception:
                        pass

            self.map_pixel_size = max(1, min(4, int(default.get("map_pixel_size", 2))))
            self.wheel_sensitivity = max(1, min(10, int(default.get("wheel_sensitivity", 5))))

            name = str(default.get("player_name", "PLAYER")).strip()
            self.player_name = (name[:12] if name else "PLAYER")
            self.player_name_input = self.player_name
            self.player_name_editing = False

        def save_options(self):
            data = {
                "map_pixel_size": self.map_pixel_size,
                "wheel_sensitivity": self.wheel_sensitivity,
                "player_name": getattr(self, "player_name", "PLAYER"),
            }
            if IS_WEB:
                try:
                    js.window.localStorage.setItem("highway_racer_options", json.dumps(data))
                except Exception:
                    pass
            else:
                try:
                    with open(self.options_file, "w") as f:
                        json.dump(data, f)
                except Exception:
                    pass

        def load_car_data(self):
            default = {
                "engine_lv":  1,
                "brake_lv":   1,
                "weight_lv":  1,
                "owned_colors": [0],   # 購入済みカラーインデックスリスト（0=WHITE無料）
                "color_idx":  0,
            }
            if IS_WEB:
                try:
                    data = js.window.localStorage.getItem("highway_racer_car_data")
                    if data:
                        loaded = json.loads(data)
                        default.update(loaded)
                except Exception:
                    pass
            else:
                if os.path.exists(self.car_data_file):
                    try:
                        with open(self.car_data_file, "r") as f:
                            loaded = json.load(f)
                            default.update(loaded)
                    except Exception:
                        pass
            # カラーを反映
            idx = default.get("color_idx", 0)
            if 0 <= idx < len(self.CAR_COLORS):
                self.car_color = self.CAR_COLORS[idx]["col"]
            return default

        def save_car_data(self):
            self.car_data["color_idx"] = self.cust_color_sel
            if IS_WEB:
                try:
                    js.window.localStorage.setItem("highway_racer_car_data", json.dumps(self.car_data))
                except Exception:
                    pass
            else:
                try:
                    with open(self.car_data_file, "w") as f:
                        json.dump(self.car_data, f)
                except Exception:
                    pass

        def get_perf_mult(self):
            """
            エンジン/ブレーキ/軽量化レベルから性能乗数を返す。
            Lv1=0.6, Lv10=1.2 の線形スケール。
            軽量化はエンジン・ブレーキ・ハンドリング全てに追加乗算。
            """
            def lv_to_mult(lv):
                # Lv1→0.60, Lv10→1.20  (step = 0.60/9 ≈ 0.0667)
                return 0.60 + (lv - 1) * (0.60 / 9.0)

            eng = lv_to_mult(self.car_data["engine_lv"])
            brk = lv_to_mult(self.car_data["brake_lv"])
            wgt = lv_to_mult(self.car_data["weight_lv"])

            # エンジン強化 → ハンドリングは反比例（最大-25%）
            eng_handling_pen = 1.0 - (self.car_data["engine_lv"] - 1) * 0.025

            return {
                "accel":    eng * wgt,            # 加速力
                "max_vel":  eng * wgt,            # 最高速
                "brake":    brk * wgt,            # ブレーキ力
                "handling": eng_handling_pen * wgt,  # ハンドリング
                "grip":     wgt,                  # グリップ
            }

