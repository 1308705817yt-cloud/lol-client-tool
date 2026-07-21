"""Tkinter 用户界面。"""

import asyncio
import queue
import time
import tkinter as tk
from tkinter import scrolledtext, ttk

import lcu_core
import shared


class Application:
    MAX_LOG_LINES = 2000
    POSITIONS = ("上单", "打野", "中单", "AD", "辅助")

    def __init__(self):
        self.root = tk.Tk()
        self.root.title("LoL 客户端工具")
        self.root.geometry("860x820")
        self.root.protocol("WM_DELETE_WINDOW", self.close)

        try:
            self.root.iconbitmap("YOUR_ICON_FILE.ico")
        except tk.TclError:
            pass

        ttk.Style().theme_use("clam")
        self.ui_tasks = queue.Queue()
        self.closed = False

        self._build_layout()
        self._register_ui_hooks()
        
        # --- 定时轮询英雄席数据 ---
        shared.CURRENT_BENCH = []
        self._last_bench = None
        self.root.after(500, self._poll_bench)
        # ------------------------
        
        self.root.after(20, self._drain_ui_tasks)
        shared.gui_print("程序已启动，可在上方选项卡中配置功能。", "sys")

    def _poll_bench(self):
        """每 0.5 秒检查一次后台读取到的英雄席数据并刷新 UI"""
        if self.closed:
            return
        
        current = getattr(shared, "CURRENT_BENCH", [])
        if current != self._last_bench:
            self._last_bench = list(current)
            self._update_bench_ui(current)
            
        self.root.after(500, self._poll_bench)

    def _build_layout(self):
        notebook = ttk.Notebook(self.root)
        notebook.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)

        game_tab = ttk.Frame(notebook)
        chat_tab = ttk.Frame(notebook)
        log_tab = ttk.Frame(notebook)
        notebook.add(game_tab, text=" 战绩与自动化 ")
        notebook.add(chat_tab, text=" 快捷发送 ")
        notebook.add(log_tab, text=" 运行日志 ")

        self._build_game_tab(game_tab)
        self._build_chat_tab(chat_tab)
        self._build_log_tab(log_tab)

        self.chat_canvas.bind_all(
            "<MouseWheel>",
            lambda event: self.chat_canvas.yview_scroll(
                int(-event.delta / 120), "units"
            ) if notebook.index(notebook.select()) == 1 else None,
        )

    def _register_ui_hooks(self):
        shared.register_ui(
            print_message=self.append_log,
            clear_log=self.clear_log,
            print_matches=self.print_matches,
            update_tree=self.update_match_tree,
            clear_tree=self.clear_match_tree,
            update_champions=self.update_champion_choices,
            update_blacklist=self.update_blacklist_choices,
            update_send_channel=self.update_send_channel,
            update_targets=self.update_target_entries,
        )

    def dispatch(self, callback, *args):
        if not self.closed:
            self.ui_tasks.put((callback, args))

    def _drain_ui_tasks(self):
        if self.closed:
            return
        for _ in range(100):
            try:
                callback, args = self.ui_tasks.get_nowait()
            except queue.Empty:
                break
            try:
                callback(*args)
            except tk.TclError:
                pass
        self.root.after(20, self._drain_ui_tasks)

    def close(self):
        self.closed = True
        self.root.destroy()

    def _build_game_tab(self, parent):
        self._build_query_panel(parent)
        self._build_blacklist_panel(parent)
        self._build_automation_panel(parent)
        self._build_aram_bench_panel(parent) 
        self._build_match_table(parent)

    def _build_query_panel(self, parent):
        frame = ttk.LabelFrame(parent, text="查询设置")
        frame.pack(padx=10, pady=5, fill=tk.X)

        ttk.Label(frame, text="对局模式:").grid(row=0, column=0, padx=5, pady=5)
        self.mode_combo = ttk.Combobox(
            frame,
            values=("单双排", "灵活排位", "海克斯大乱斗", "大乱斗", "匹配", "全部"),
            state="readonly",
            width=12,
        )
        self.mode_combo.set(shared.CURRENT_CONFIG["查询模式"])
        self.mode_combo.grid(row=0, column=1, padx=5, pady=5)

        ttk.Label(frame, text="最近场数:").grid(row=0, column=2, padx=5, pady=5)
        self.count_combo = ttk.Combobox(
            frame, values=("3", "5", "8", "10"), state="readonly", width=5
        )
        self.count_combo.set(str(shared.CURRENT_CONFIG["查询场数"]))
        self.count_combo.grid(row=0, column=3, padx=5, pady=5)

        for combo in (self.mode_combo, self.count_combo):
            combo.bind("<<ComboboxSelected>>", self._save_query_settings)

        ttk.Button(frame, text="重新查询", command=self._manual_requery).grid(
            row=0, column=4, padx=15, pady=5
        )

        titles = ttk.Frame(frame)
        titles.grid(row=1, column=0, columnspan=5, padx=5, pady=5, sticky=tk.W)
        ttk.Label(titles, text="KDA 分级:").pack(side=tk.LEFT, padx=(0, 5))

        configured = shared.CURRENT_CONFIG["KDA称号"]
        self.title_entries = []
        for index in range(5):
            ttk.Label(titles, text=f"{index + 1}.").pack(side=tk.LEFT)
            entry = ttk.Entry(titles, width=8)
            entry.insert(0, configured[index] if index < len(configured) else f"称号{index + 1}")
            entry.pack(side=tk.LEFT, padx=(2, 12))
            entry.bind("<FocusOut>", self._save_titles)
            entry.bind("<Return>", self._save_titles)
            self.title_entries.append(entry)

    def _save_query_settings(self, _event=None):
        shared.CURRENT_CONFIG.update(
            {"查询模式": self.mode_combo.get(), "查询场数": int(self.count_combo.get())}
        )
        shared.save_config()

    def _save_titles(self, _event=None):
        shared.CURRENT_CONFIG["KDA称号"] = [
            entry.get().strip() or f"称号{index + 1}"
            for index, entry in enumerate(self.title_entries)
        ]
        shared.save_config()

    def _manual_requery(self):
        if not lcu_core.GLOBAL_CONN or not lcu_core.GLOBAL_LOOP:
            shared.gui_print("客户端仍在连接中，请稍后重试。", "loss")
            return
        shared.gui_print("正在向客户端发送查询请求...", "info")
        try:
            asyncio.run_coroutine_threadsafe(
                lcu_core.manual_requery_task(), lcu_core.GLOBAL_LOOP
            )
        except Exception as exc:
            shared.gui_print(f"查询任务启动失败: {exc}", "loss")

    def _build_blacklist_panel(self, parent):
        frame = ttk.LabelFrame(parent, text="玩家备注")
        frame.pack(padx=10, pady=5, fill=tk.X)

        ttk.Label(frame, text="选择/输入玩家:").grid(row=0, column=0, padx=5, pady=5)
        self.blacklist_combo = ttk.Combobox(frame, width=35)
        self.blacklist_combo["values"] = self._current_player_choices()
        self.blacklist_combo.grid(row=0, column=1, padx=5, pady=5)
        ttk.Button(frame, text="清空", command=self._clear_blacklist).grid(
            row=0, column=2, padx=15, pady=5
        )

        ttk.Label(frame, text="备注(选填):").grid(row=1, column=0, padx=5, pady=5)
        self.reason_entry = ttk.Entry(frame, width=37)
        self.reason_entry.grid(row=1, column=1, padx=5, pady=5)
        ttk.Button(frame, text="添加记录", command=self._add_blacklist).grid(
            row=1, column=2, padx=15, pady=5
        )

    @staticmethod
    def _current_player_choices():
        return [
            f"{player['name']}({player['champ']})"
            for player in shared.LAST_MATCH_PLAYERS_DICT.values()
        ]

    def _clear_blacklist(self):
        shared.CURRENT_CONFIG["黑名单"] = {}
        shared.save_config()
        shared.gui_print("玩家备注已清空。", "success")

    def _add_blacklist(self):
        selected = self.blacklist_combo.get().strip()
        if not selected:
            return

        name = selected.split("(", 1)[0].strip()
        player = shared.LAST_MATCH_PLAYERS_DICT.get(name, {})
        champion = player.get("champ", "未知英雄")
        kda = player.get("kda_str", "?/?/?")
        mode = player.get("mode", "未知模式")
        reason = self.reason_entry.get().strip()
        timestamp = time.strftime("%Y年%m月%d日 %H:%M")
        record = f"{name}在{timestamp}的【{mode}】中使用{champion}取得{kda}的战绩"
        record += f"，并且{reason}" if reason else ""
        record += "。"

        blacklist = shared.CURRENT_CONFIG.get("黑名单", {})
        if isinstance(blacklist, list):
            blacklist = {item: "无历史记录" for item in blacklist}
        previous = blacklist.get(name, "")
        blacklist[name] = f"{previous}\n{record}".strip() if previous else record
        shared.CURRENT_CONFIG["黑名单"] = blacklist
        shared.save_config()

        self.blacklist_combo.set("")
        self.reason_entry.delete(0, tk.END)
        shared.gui_print(f"已记录玩家【{name}】。", "success")

    def _build_automation_panel(self, parent):
        frame = ttk.LabelFrame(parent, text="自动化设定 (支持拼音搜索)")
        frame.pack(padx=10, pady=5, fill=tk.X)

        self.auto_accept = tk.BooleanVar(value=shared.CURRENT_CONFIG.get("自动接受", False))
        self.auto_ban = tk.BooleanVar(value=shared.CURRENT_CONFIG.get("自动禁用", False))
        self.auto_pick = tk.BooleanVar(value=shared.CURRENT_CONFIG.get("自动选择", False))

        ttk.Checkbutton(
            frame, text="秒接对局", variable=self.auto_accept, command=self._save_automation
        ).grid(row=0, column=0, padx=10, pady=5)
        ttk.Checkbutton(
            frame, text="自动Ban:", variable=self.auto_ban, command=self._save_automation
        ).grid(row=0, column=1, padx=(10, 0), pady=5)

        champion_values = [champ.display_name for champ in shared.ALL_CHAMPS]
        self.ban_combo = ttk.Combobox(frame, values=champion_values, width=18)
        self.ban_combo.set(shared.CURRENT_CONFIG.get("禁用英雄", ""))
        self.ban_combo.grid(row=0, column=2, padx=5, pady=5)

        ttk.Checkbutton(
            frame, text="自动秒选:", variable=self.auto_pick, command=self._save_automation
        ).grid(row=0, column=3, padx=(10, 0), pady=5)
        self.pick_combo = ttk.Combobox(frame, values=champion_values, width=18)
        self.pick_combo.set(shared.CURRENT_CONFIG.get("选择英雄", ""))
        self.pick_combo.grid(row=0, column=4, padx=5, pady=5)

        for combo in (self.ban_combo, self.pick_combo):
            combo.bind("<KeyRelease>", lambda event, box=combo: self._filter_champions(event, box))
            combo.bind("<Return>", lambda event, box=combo: self._complete_champion(box))
            combo.bind("<FocusOut>", lambda event, box=combo: self._complete_champion(box))
            combo.bind("<<ComboboxSelected>>", self._save_automation)

    def _save_automation(self, _event=None):
        shared.CURRENT_CONFIG.update(
            {
                "自动接受": self.auto_accept.get(),
                "自动禁用": self.auto_ban.get(),
                "自动选择": self.auto_pick.get(),
                "禁用英雄": self.ban_combo.get().strip(),
                "选择英雄": self.pick_combo.get().strip(),
            }
        )
        shared.save_config()

    def _filter_champions(self, event, combo):
        if event.keysym in {"Up", "Down", "Left", "Right", "Return", "Tab"}:
            return
        query = combo.get().lower().strip()
        combo["values"] = [
            champ.display_name
            for champ in shared.ALL_CHAMPS
            if not query or query in champ.search_keys
        ]

    def _complete_champion(self, combo):
        query = combo.get().lower().strip()
        match = next(
            (champ.display_name for champ in shared.ALL_CHAMPS if query in champ.search_keys),
            None,
        ) if query else None
        if match:
            combo.set(match)
            combo.icursor(tk.END)
        self._save_automation()

    def _build_aram_bench_panel(self, parent):
        self.bench_frame = ttk.LabelFrame(parent, text="大乱斗实时英雄席 (点击秒抢，无视冷却)")
        self.bench_frame.pack(padx=10, pady=5, fill=tk.X)
        self._set_bench_placeholder()

    def _set_bench_placeholder(self):
        for widget in self.bench_frame.winfo_children():
            widget.destroy()
        ttk.Label(
            self.bench_frame, 
            text="匹配进入大乱斗选人界面后，这里会自动显示池子里的英雄供您一键抢夺..."
        ).pack(padx=5, pady=8)

    def _update_bench_ui(self, bench_champions):
        # 清空原有的按钮或文本
        for widget in self.bench_frame.winfo_children():
            widget.destroy()
            
        if not bench_champions:
            self._set_bench_placeholder()
            return
            
        # 动态生成当前可供抢夺的英雄按钮
        for index, champ_id in enumerate(bench_champions):
            champ_name = shared.CHAMPION_DICT.get(champ_id, f"英雄{champ_id}")
            btn = tk.Button(
                self.bench_frame,
                text=champ_name,
                width=10,
                height=2,
                cursor="hand2",
                bg="#e8f4f8",
                activebackground="#a8e6cf",
                command=lambda cid=champ_id: self._grab_bench_champion(cid)
            )
            btn.grid(row=index // 6, column=index % 6, padx=8, pady=8)
            
    def _grab_bench_champion(self, champ_id):
        if lcu_core.GLOBAL_CONN and lcu_core.GLOBAL_LOOP:
            asyncio.run_coroutine_threadsafe(
                lcu_core.execute_bench_swap(champ_id),
                lcu_core.GLOBAL_LOOP
            )
        else:
            shared.gui_print("与客户端断开连接，无法执行请求。", "loss")

    def _build_match_table(self, parent):
        frame = ttk.LabelFrame(parent, text="实时对局信息（进入游戏后自动刷新）")
        frame.pack(padx=10, pady=5, fill=tk.BOTH, expand=True)

        columns = ("队伍", "玩家ID", "英雄", "段位", "KDA", "胜率")
        self.match_tree = ttk.Treeview(frame, columns=columns, show="headings", height=10)
        definitions = (
            ("队伍", "阵营", 60), ("玩家ID", "玩家ID", 140),
            ("英雄", "英雄", 90), ("段位", "段位 (单双/灵活)", 160),
            ("KDA", "近期KDA", 70), ("胜率", "近期胜率(20场)", 80),
        )
        for column, title, width in definitions:
            self.match_tree.heading(column, text=title)
            anchor = tk.W if column == "玩家ID" else tk.CENTER
            self.match_tree.column(column, width=width, anchor=anchor)

        scrollbar = ttk.Scrollbar(frame, orient=tk.VERTICAL, command=self.match_tree.yview)
        self.match_tree.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.match_tree.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

    def _build_chat_tab(self, parent):
        self.chat_canvas = tk.Canvas(parent, borderwidth=0, highlightthickness=0)
        scrollbar = ttk.Scrollbar(parent, orient="vertical", command=self.chat_canvas.yview)
        content = ttk.Frame(self.chat_canvas)
        content.bind(
            "<Configure>",
            lambda _event: self.chat_canvas.configure(
                scrollregion=self.chat_canvas.bbox("all")
            ),
        )
        window = self.chat_canvas.create_window((0, 0), window=content, anchor="nw")
        self.chat_canvas.bind(
            "<Configure>",
            lambda event: self.chat_canvas.itemconfigure(window, width=event.width),
        )
        self.chat_canvas.configure(yscrollcommand=scrollbar.set)
        self.chat_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        self._build_split_panel(content)
        self._build_target_panel(content)

    def _build_split_panel(self, parent):
        frame = ttk.LabelFrame(
            parent, text="预设快捷发送（小键盘 0 固定句，小键盘 . 随机句）"
        )
        frame.pack(padx=10, pady=5, fill=tk.X)

        self.split_enabled = tk.BooleanVar(
            value=shared.CURRENT_CONFIG.get("拆字发送开关", False)
        )
        self.split_all = tk.BooleanVar(
            value=shared.CURRENT_CONFIG.get("拆字发所有人", True)
        )
        ttk.Checkbutton(
            frame, text="启用连发", variable=self.split_enabled, command=self._save_split
        ).grid(row=0, column=0, padx=5, pady=5)
        ttk.Checkbutton(
            frame, text="发所有人(小键盘6)", variable=self.split_all, command=self._save_split
        ).grid(row=0, column=1, padx=5, pady=5)

        ttk.Label(frame, text="每次发送:").grid(row=0, column=2)
        range_frame = ttk.Frame(frame)
        range_frame.grid(row=0, column=3, padx=2)
        self.split_min = ttk.Entry(range_frame, width=3)
        self.split_min.insert(0, str(shared.CURRENT_CONFIG.get("拆字最小字数", 1)))
        self.split_min.pack(side=tk.LEFT)
        ttk.Label(range_frame, text="~").pack(side=tk.LEFT)
        self.split_max = ttk.Entry(range_frame, width=3)
        self.split_max.insert(0, str(shared.CURRENT_CONFIG.get("拆字最大字数", 1)))
        self.split_max.pack(side=tk.LEFT)
        ttk.Label(range_frame, text="字").pack(side=tk.LEFT)

        ttk.Label(frame, text="发送速度:").grid(row=0, column=4, padx=(5, 0))
        self.split_speed = ttk.Combobox(
            frame,
            values=("档位1 (极慢)", "档位2 (较慢)", "档位3 (正常)", "档位4 (较快)", "档位5 (极速)"),
            state="readonly",
            width=12,
        )
        self.split_speed.set(shared.CURRENT_CONFIG.get("拆字发送速度", "档位3 (正常)"))
        self.split_speed.grid(row=0, column=5, padx=2)
        self.split_speed.bind("<<ComboboxSelected>>", self._save_split)

        ttk.Label(frame, text="固定单句 (小键盘0):").grid(row=1, column=0, padx=5)
        self.fixed_sentence = ttk.Entry(frame, width=50)
        self.fixed_sentence.insert(0, shared.CURRENT_CONFIG.get("预设单句", ""))
        self.fixed_sentence.grid(row=1, column=1, columnspan=5, padx=5, pady=2)

        ttk.Label(frame, text="随机句子库 (小键盘.):\n每行一句").grid(
            row=2, column=0, padx=5, pady=2
        )
        self.sentence_pool = tk.Text(frame, height=4, width=50)
        self.sentence_pool.insert("1.0", shared.CURRENT_CONFIG.get("句子库", ""))
        self.sentence_pool.grid(row=2, column=1, columnspan=5, padx=5, pady=2)

        for widget in (self.split_min, self.split_max, self.fixed_sentence, self.sentence_pool):
            widget.bind("<FocusOut>", self._save_split)

    def _save_split(self, _event=None):
        try:
            minimum = max(1, int(self.split_min.get().strip()))
            maximum = max(minimum, int(self.split_max.get().strip()))
        except ValueError:
            shared.gui_print("每次发送字数必须是整数。", "loss")
            return

        shared.CURRENT_CONFIG.update(
            {
                "拆字发送开关": self.split_enabled.get(),
                "拆字发所有人": self.split_all.get(),
                "拆字最小字数": minimum,
                "拆字最大字数": maximum,
                "拆字发送速度": self.split_speed.get(),
                "预设单句": self.fixed_sentence.get().strip(),
                "句子库": self.sentence_pool.get("1.0", tk.END).strip(),
            }
        )
        shared.save_config()

    def _build_target_panel(self, parent):
        switch_frame = ttk.LabelFrame(parent, text="目标选择")
        switch_frame.pack(padx=10, pady=5, fill=tk.X)
        self.target_enabled = tk.BooleanVar(
            value=shared.CURRENT_CONFIG.get("指名道姓开关", False)
        )
        ttk.Checkbutton(
            switch_frame,
            text="使用小键盘 1~5 选择目标（发送后有 3 秒选择窗口）",
            variable=self.target_enabled,
            command=self._save_targets,
        ).pack(anchor=tk.W, padx=5, pady=5)

        frame = ttk.LabelFrame(parent, text="局内目标称呼")
        frame.pack(padx=10, pady=5, fill=tk.X)
        self.target_entries = {}
        for row, side in ((0, "敌方"), (3, "己方")):
            ttk.Label(frame, text=f"【{side}】").grid(
                row=row, column=0, columnspan=5, sticky=tk.W, padx=5, pady=2
            )
            for column, position in enumerate(self.POSITIONS):
                ttk.Label(frame, text=position).grid(row=row + 1, column=column, padx=5)
                key = f"{side}{position}"
                entry = ttk.Entry(frame, width=12)
                entry.insert(0, shared.CURRENT_CONFIG.get(f"目标_{key}", key))
                entry.grid(row=row + 2, column=column, padx=5, pady=2)
                entry.bind("<FocusOut>", self._save_targets)
                self.target_entries[key] = entry

    def _save_targets(self, _event=None):
        shared.CURRENT_CONFIG["指名道姓开关"] = self.target_enabled.get()
        for key, entry in self.target_entries.items():
            shared.CURRENT_CONFIG[f"目标_{key}"] = entry.get().strip()
        shared.save_config()

    def _build_log_tab(self, parent):
        self.log = scrolledtext.ScrolledText(
            parent,
            wrap=tk.WORD,
            font=("Microsoft YaHei", 10, "bold"),
            bg="#1e1e1e",
            fg="#d4d4d4",
        )
        self.log.pack(padx=15, pady=15, fill=tk.BOTH, expand=True)
        colors = {
            "sys": "#6b6b6b", "info": "#b19cd9", "success": "#a8e6cf",
            "player": "#00E5FF", "rank": "#FFD700", "win": "#4CAF50",
            "loss": "#FF5252",
        }
        for tag, color in colors.items():
            self.log.tag_config(tag, foreground=color)
        self.log.config(state=tk.DISABLED)

    def append_log(self, message, color_tag=None):
        self.dispatch(self._append_log, str(message), color_tag)

    def _append_log(self, message, color_tag):
        self.log.config(state=tk.NORMAL)
        if color_tag:
            self.log.insert(tk.END, message + "\n", color_tag)
        else:
            self.log.insert(tk.END, message + "\n")
        self._trim_log()
        self.log.see(tk.END)
        self.log.config(state=tk.DISABLED)

    def _trim_log(self):
        line_count = int(self.log.index("end-1c").split(".")[0])
        if line_count > self.MAX_LOG_LINES:
            self.log.delete("1.0", f"{line_count - self.MAX_LOG_LINES + 1}.0")

    def clear_log(self):
        self.dispatch(self._clear_log)

    def _clear_log(self):
        self.log.config(state=tk.NORMAL)
        self.log.delete("1.0", tk.END)
        self.log.config(state=tk.DISABLED)

    def print_matches(self, matches):
        self.dispatch(self._print_matches, list(matches))

    def _print_matches(self, matches):
        self.log.config(state=tk.NORMAL)
        self.log.insert(tk.END, "   最近战绩: ")
        for index, match in enumerate(matches):
            self.log.insert(tk.END, match, "win" if "胜" in match else "loss")
            if index < len(matches) - 1:
                self.log.insert(tk.END, " | ", "sys")
        self.log.insert(tk.END, "\n")
        self._trim_log()
        self.log.see(tk.END)
        self.log.config(state=tk.DISABLED)

    def update_match_tree(self, allies, enemies):
        self.dispatch(self._update_match_tree, list(allies), list(enemies))

    def _update_match_tree(self, allies, enemies):
        self._clear_match_tree()
        for row in allies:
            self.match_tree.insert("", tk.END, values=row, tags=("ally",))
        self.match_tree.insert("", tk.END, values=("-----",) * 6)
        for row in enemies:
            self.match_tree.insert("", tk.END, values=row, tags=("enemy",))
        self.match_tree.tag_configure("ally", background="#e8f4f8")
        self.match_tree.tag_configure("enemy", background="#fcecec")

    def clear_match_tree(self):
        self.dispatch(self._clear_match_tree)

    def _clear_match_tree(self):
        for item in self.match_tree.get_children():
            self.match_tree.delete(item)

    def update_champion_choices(self):
        self.dispatch(self._update_champion_choices)

    def _update_champion_choices(self):
        values = [champ.display_name for champ in shared.ALL_CHAMPS]
        self.ban_combo.configure(values=values)
        self.pick_combo.configure(values=values)

    # --- 核心修复：更新黑名单组合框时，修复参数传递导致的崩溃 ---
    def update_blacklist_choices(self, players):
        self.dispatch(lambda: self.blacklist_combo.configure(values=list(players)))
    # ------------------------------------------------------------

    def update_send_channel(self, send_to_all):
        self.dispatch(self.split_all.set, send_to_all)

    def update_target_entries(self, targets):
        self.dispatch(self._update_target_entries, dict(targets))

    def _update_target_entries(self, targets):
        for key, value in targets.items():
            entry = self.target_entries.get(key)
            if entry:
                entry.delete(0, tk.END)
                entry.insert(0, value)

    def run(self):
        self.root.mainloop()


def start_gui():
    Application().run()