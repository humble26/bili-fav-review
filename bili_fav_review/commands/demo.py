"""demo：内置演示数据，不登录不花钱也能体验复习/搜索全流程。"""

import json
from datetime import date, timedelta

from .. import ui
from ..config import load_config
from ..paths import db_path
from ..store import Store


def _card(one_liner, kps, kws, quiz):
    return json.dumps(
        {"one_liner": one_liner, "key_points": kps, "keywords": kws, "quiz": quiz},
        ensure_ascii=False,
    )


DEMO = [
    {
        "bvid": "BV1DemoA001",
        "aid": 9000001,
        "title": "为什么你的收藏夹在吃灰？——认知科学解读「收藏即学会」幻觉",
        "intro": "点击收藏的那一刻大脑会误以为完成了学习，这叫数字囤积错觉。真正的学习需要提取练习。",
        "upper_name": "硬核科普君",
        "duration": 612,
        "fav_time": 1757400000,
        "pubtime": 1757300000,
        "subtitle_lang": "ai-zh",
        "transcript": "[00:00] 大家好，你有没有过这种经历：刷到一个干货视频，激动地点了收藏，然后再也没打开过。\n[00:15] 认知科学里这叫“收藏即学会”幻觉。点收藏的动作会让大脑分泌少量多巴胺，产生“任务已完成”的错觉。\n[00:40] 真正的学习发生在提取练习的时候：合上视频，主动回忆内容，记忆才会被加固。\n[01:10] 所以收藏夹的正确用法不是仓库，而是复习队列：今天收藏，明天回忆一次，三天后再回忆一次。\n[01:45] 实验数据表明，一次主动回忆的效果胜过重看三遍视频。\n[02:20] 这就是为什么本频道说：收藏不如复习，复习不如测试自己。",
        "summary_json": _card(
            "点收藏带来的完成感是大脑的错觉，只有主动回忆（提取练习）才能真正形成记忆。",
            ["收藏动作会制造“任务已完成”的多巴胺错觉", "提取练习（主动回忆）才是记忆加固的关键", "一次主动回忆胜过重看三遍", "收藏夹应当作复习队列而非仓库使用"],
            ["认知科学", "提取练习", "数字囤积"],
            [{"question": "为什么点收藏会让人觉得“已经学会了”？", "answer": "收藏动作分泌多巴胺，制造任务完成的错觉，学习并未发生"}],
        ),
    },
    {
        "bvid": "BV1DemoB002",
        "aid": 9000002,
        "title": "10分钟搞懂艾宾浩斯遗忘曲线：记忆是怎么溜走的",
        "intro": "遗忘在学习后立即开始且先快后慢，间隔重复是对抗遗忘曲线最有效的手段之一。",
        "upper_name": "心理小课堂",
        "duration": 604,
        "fav_time": 1757400000,
        "pubtime": 1757200000,
        "subtitle_lang": "zh-Hans",
        "transcript": "[00:00] 1885年，艾宾浩斯用无意义音节做了记忆实验，画出了一条著名的曲线。\n[00:30] 结论是：遗忘在学习之后立即开始，而且先快后慢。20分钟后忘掉42%，一天后忘掉约66%。\n[01:20] 但同样的内容，如果分散在多天复习，记忆保持率会大幅上升，这就是间隔效应。\n[02:00] 现代的间隔重复算法（如SM-2）会根据你的回忆质量动态调整下次复习时间：记得牢就隔久一点，忘了就明天再见。\n[03:10] 记住一个数：每次成功回忆后，安全间隔大约翻倍，这就是你击败遗忘曲线的方式。",
        "summary_json": _card(
            "遗忘先快后慢；用间隔重复（记得牢就拉长间隔）对抗遗忘曲线是最高效的记忆策略。",
            ["遗忘在学习后立即开始，20分钟后忘掉约42%", "间隔效应：分散复习的保持率远高于集中突击", "SM-2 等算法按回忆质量动态安排下次复习时间", "每次成功回忆后安全间隔大约翻倍"],
            ["艾宾浩斯", "间隔重复", "SM-2"],
            [{"question": "艾宾浩斯曲线的核心结论是什么？", "answer": "遗忘立即开始且先快后慢，因此复习要赶在大幅遗忘之前进行"}, {"question": "间隔重复算法如何决定下次复习时间？", "answer": "根据回忆质量：记得牢则拉长间隔（约翻倍），忘了则重置为短间隔"}],
        ),
    },
    {
        "bvid": "BV1DemoC003",
        "aid": 9000003,
        "title": "维多利亚3入门：19世纪经济模拟器到底在模拟什么",
        "intro": "V3模拟的不是战争而是经济：人口、市场、利益集团三大系统互相咬合。",
        "upper_name": "P社萌新指南",
        "duration": 893,
        "fav_time": 1757400000,
        "pubtime": 1757100000,
        "subtitle_lang": "ai-zh",
        "transcript": "[00:00] 很多人以为维多利亚3是打仗游戏，其实它本质上是一个19世纪经济学模拟器。\n[00:25] 三大核心系统：人口（Pop）、市场、利益集团。你颁布的每一项法令，最终都通过这三者互相传导。\n[01:05] 建造地产产生就业，就业改变人群的财富与政治倾向，政治倾向又影响利益集团的力量对比。\n[02:10] 所以V3的战争反而很克制：战争是经济矛盾激化后的结果，而不是目的。\n[03:30] 给新手的建议：前期盯着建筑力和市场供需，别急着扩张领土。",
        "summary_json": _card(
            "V3 是经济模拟器：人口-市场-利益集团三大系统咬合传导，战争只是矛盾的溢出。",
            ["核心三系统：人口 Pop、市场、利益集团", "法令→就业→财富→政治倾向→集团力量的传导链", "战争是经济矛盾激化的结果而非目的", "新手前期优先关注建筑力与市场供需"],
            ["维多利亚3", "经济系统", "利益集团"],
            [{"question": "V3 的三大核心系统是什么？", "answer": "人口（Pop）、市场、利益集团"}],
        ),
    },
    {
        "bvid": "BV1DemoD004",
        "aid": 9000004,
        "title": "拖延症的神经科学：多巴胺、deadline 与最后一分钟",
        "intro": "拖延不是时间管理问题，而是情绪调节问题；大脑在回避任务带来的负面情绪。",
        "upper_name": "脑科学观察",
        "duration": 745,
        "fav_time": 1757400000,
        "pubtime": 1757000000,
        "subtitle_lang": "ai-zh",
        "transcript": "[00:00] 拖延的本质不是懒，而是情绪调节：大脑在回避任务附带的焦虑、无聊或自我怀疑。\n[00:35] 边缘系统（即时满足）与前额叶（长期规划）的拉锯战，决定了你是打开文档还是打开视频。\n[01:30] deadline 为什么有用？因为它把遥远任务的未来惩罚变成了迫在眉睫的即时威胁。\n[02:20] 实用技巧一：把任务切到“5分钟就能开始”的粒度，绕过启动阻力。\n[03:00] 实用技巧二：自我原谅。研究表明原谅自己上次拖延的人，下次拖延更少。",
        "summary_json": _card(
            "拖延是情绪调节问题而非时间管理问题：大脑在回避任务带来的负面情绪。",
            ["拖延的本质是回避焦虑/无聊等负面情绪", "边缘系统追求即时满足，与前额叶长期规划拉锯", "deadline 之所以有效，是把未来惩罚变成即时威胁", "把任务切到5分钟粒度可绕过启动阻力", "自我原谅反而能减少下次拖延"],
            ["拖延症", "情绪调节", "前额叶"],
            [{"question": "为什么说拖延不是时间管理问题？", "answer": "它是情绪调节问题，大脑在回避任务引发的负面情绪"}, {"question": "两个立即可用的反拖延技巧？", "answer": "任务切到5分钟启动粒度；对上次的拖延进行自我原谅"}],
        ),
    },
]


def run(args) -> int:
    cfg, _ = load_config(args.config)
    store = Store(db_path(cfg))
    try:
        if getattr(args, "clear", False):
            n = store.clear_demo()
            ui.success(f"已清除演示数据（{n} 行）")
            return 0

        today = date.today()
        due_offsets = [0, 0, 2, 5]
        for v, off in zip(DEMO, due_offsets):
            v = dict(v)
            v["folder_title"] = "演示收藏夹"
            v["folder_id"] = -1
            v["added_at"] = int(today.strftime("%Y%m%d"))
            store.insert_demo_video(v)
            store.init_review(v["bvid"], (today + timedelta(days=off)).isoformat())
        ui.success("演示数据已就绪：4 张卡片（2 张今天到期）")
        ui.info("试试这些命令：")
        ui.info("  python -m bili_fav_review review    # 开始复习")
        ui.info("  python -m bili_fav_review search 遗忘")
        ui.info("  python -m bili_fav_review stats")
        ui.info("清除演示数据: python -m bili_fav_review demo --clear")
        return 0
    finally:
        store.close()
