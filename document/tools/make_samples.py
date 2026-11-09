"""生成 samples/ 下的示例文档（手写内容，供金样、测试与产出台原型使用）。"""
import json
from pathlib import Path

from synth import b64png

ROOT = Path(__file__).resolve().parents[1]
FONT = "font-family=\"Noto Sans SC, PingFang SC, Microsoft YaHei, sans-serif\""


def arch_svg():
    layers = [("应用层", ["物业值班台", "居民小程序", "街道监管端"], "#e8f0fb"),
              ("平台层", ["视频管理平台", "告警中心", "数据中台"], "#eaf6ee"),
              ("网络层", ["光纤环网", "4G 备份链路"], "#fdf3e4"),
              ("感知层", ["高清摄像机", "人脸门禁", "烟感与水浸"], "#f4ecf8")]
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 640 380" width="640" height="380" {FONT} font-size="14">',
           '<rect width="640" height="380" fill="#ffffff"/>']
    y = 14
    for name, boxes, fill in layers:
        out.append(f'<rect x="10" y="{y}" width="620" height="76" rx="8" fill="{fill}" stroke="#9aa4b2"/>')
        out.append(f'<text x="28" y="{y + 44}" font-weight="bold" fill="#333">{name}</text>')
        n = len(boxes)
        w = (500 - (n - 1) * 14) / n
        for i, b in enumerate(boxes):
            x = 115 + i * (w + 14)
            out.append(f'<rect x="{x:.1f}" y="{y + 16}" width="{w:.1f}" height="44" rx="6" fill="#ffffff" stroke="#6b7a90"/>')
            out.append(f'<text x="{x + w / 2:.1f}" y="{y + 43}" text-anchor="middle" fill="#222">{b}</text>')
        if name != "感知层":
            out.append(f'<path d="M320 {y + 77} v14" stroke="#6b7a90" stroke-width="2" marker-end="url(#a)"/>')
        y += 92
    out.insert(2, '<defs><marker id="a" viewBox="0 0 10 10" refX="5" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">'
                  '<path d="M0 0 L10 5 L0 10 z" fill="#6b7a90"/></marker></defs>')
    out.append("</svg>")
    return "".join(out)


def gantt_svg():
    tasks = [("现场勘察", 1, 2), ("深化设计", 2, 4), ("设备采购", 3, 6), ("施工安装", 5, 10), ("联调测试", 9, 11), ("验收交付", 11, 12)]
    x0, cw, rh = 110, 42, 32
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 640 250" width="640" height="250" {FONT} font-size="13">',
           '<rect width="640" height="250" fill="#ffffff"/>']
    for w in range(12):
        x = x0 + w * cw
        out.append(f'<rect x="{x}" y="10" width="{cw}" height="22" fill="{"#f2f4f7" if w % 2 else "#e9edf2"}"/>')
        out.append(f'<text x="{x + cw / 2}" y="26" text-anchor="middle" fill="#555">第{w + 1}周</text>')
        out.append(f'<line x1="{x}" y1="32" x2="{x}" y2="{36 + len(tasks) * rh}" stroke="#e1e5ea"/>')
    for i, (name, a, b) in enumerate(tasks):
        y = 40 + i * rh
        out.append(f'<text x="{x0 - 10}" y="{y + 17}" text-anchor="end" fill="#222">{name}</text>')
        out.append(f'<rect x="{x0 + (a - 1) * cw + 2}" y="{y + 4}" width="{(b - a + 1) * cw - 4}" height="18" rx="4" fill="#3b78c4"/>')
    out.append(f'<path d="M{x0 + 11 * cw + 21} 34 l-6 -8 h12 z" fill="#d0473b"/>')
    out.append(f'<text x="{x0 + 11 * cw + 21}" y="{60 + len(tasks) * rh}" text-anchor="middle" fill="#d0473b">竣工</text>')
    out.append("</svg>")
    return "".join(out)


BID = {
    "title": "城东街道智慧社区安防改造项目",
    "subtitle": "投标文件 · 技术部分",
    "meta": {"org": "某某智能科技有限公司", "date": "2026-10-03", "version": "V1.0",
             "numbering": "chapter", "figure_numbering": "chapter", "cover": True, "toc": True, "trace_table": True},
    "requirements": [
        {"id": "r1", "text": "★ 视频监控覆盖小区出入口、主干道与地下车库，录像保存不少于 90 天", "source": "招标文件 第三章 3.2.1",
         "priority": "must", "anchor": {"page": 18}},
        {"id": "r2", "text": "★ 系统与街道现有平台对接，提供标准接口", "source": "招标文件 第三章 3.2.4", "priority": "must",
         "anchor": {"page": 19}},
        {"id": "r3", "text": "★ 总工期不超过 90 日历天", "source": "招标文件 第二章 2.5", "priority": "must", "anchor": {"page": 9}},
        {"id": "r4", "text": "★ 项目经理具有机电工程二级及以上注册建造师资格", "source": "招标文件 第二章 2.8", "priority": "must",
         "anchor": {"page": 11}},
        {"id": "r5", "text": "提供不少于 3 年的免费质保与 7×24 小时响应", "source": "招标文件 第三章 3.5", "priority": "must",
         "anchor": {"page": 22}},
        {"id": "r6", "text": "鼓励提供居民端便民服务功能", "source": "招标文件 第三章 3.3", "priority": "should", "anchor": {"page": 20}},
    ],
    "sections": [
        {"id": "overview", "heading": "项目理解", "body":
            "城东街道下辖 6 个老旧小区，现有监控以单点录像为主，设备老化、覆盖不全，告警依赖人工巡查。"
            "本项目的目标是建成**统一接入、分级告警、街道可监管**的社区安防体系。\n\n"
            "我方对项目的理解归纳为三点：\n\n"
            "1. 覆盖要全：出入口、主干道、地下车库三类重点区域无死角；\n"
            "2. 平台要通：与街道现有平台对接，数据按标准接口上报；\n"
            "3. 工期要稳：老旧小区施工扰民敏感，须分区分段、夜间不施工。\n\n"
            "总体方案见[[sec:design]]，进度安排见[[sec:schedule]]。"},
        {"id": "design", "heading": "总体设计", "body": "系统按四层架构设计，各层职责清晰、接口标准，见[[fig:arch]]。\n\n[[fig:arch]]\n\n"
            "架构遵循“前端智能、边缘汇聚、平台统一”的原则：前端设备完成目标识别，汇聚节点做本地存储与转发，平台层统一管理与告警。",
         "responds_to": ["r2"]},
        {"id": "video", "level": 2, "heading": "视频监控子系统", "body":
            "在 6 个小区共布设高清摄像机 186 台，覆盖全部出入口、主干道与地下车库，主要设备见[[tab:devices]]。\n\n"
            "[[tab:devices]]\n\n"
            "录像采用边缘存储加中心备份：前端汇聚节点按 4 Mbps 码流、7×24 小时录像配置存储，单路保存 **90 天**；"
            "重点点位同步备份至街道中心。",
         "responds_to": ["r1"]},
        {"id": "access", "level": 2, "heading": "门禁与告警子系统", "body":
            "出入口部署人脸门禁 24 套，楼栋单元门保留原有刷卡方式并接入平台。烟感、水浸等告警统一推送至告警中心，按三级处置：\n\n"
            "- 一级（火警、水浸）：值班台声光告警，3 分钟内电话通知物业主管；\n"
            "- 二级（设备离线）：值班台提示，当班处理；\n"
            "- 三级（一般事件）：汇总进日报。"},
        {"id": "interface", "level": 2, "heading": "平台对接", "body":
            "平台按街道现有平台的接口规范对接，视频接入采用国家标准协议，告警与设备状态以接口方式推送。"
            "对接内容、频率与责任分工在深化设计阶段与街道信息中心逐项确认，形成对接说明书。",
         "responds_to": ["r2"]},
        {"id": "resident", "level": 2, "heading": "居民端服务", "body":
            "居民小程序提供访客预约、报事报修、告警通知三项功能，与物业工单打通。",
         "responds_to": ["r6"]},
        {"id": "schedule", "heading": "施工组织与进度", "body":
            "总工期 **84 日历天**，分六个阶段推进，见[[fig:gantt]]。施工按小区分批进行，每个小区封闭作业不超过 10 天，夜间 20:00 后不施工。\n\n"
            "[[fig:gantt]]\n\n"
            "关键节点：第 6 周末设备全部到场，第 10 周末完成安装，第 12 周完成联调与验收。",
         "responds_to": ["r3"]},
        {"id": "team", "heading": "项目团队", "body":
            "项目实行项目经理负责制，主要人员见[[tab:staff]]。项目经理持机电工程一级注册建造师证书，"
            "近三年主持完成同类社区安防项目 4 个。\n\n[[tab:staff]]",
         "responds_to": ["r4"]},
        {"id": "service", "heading": "质保与售后服务", "body":
            "我方承诺：\n\n"
            "- 免费质保 **5 年**，自终验合格之日起计算；\n"
            "- 7×24 小时服务热线，接报后 30 分钟内远程响应，2 小时内到场；\n"
            "- 每季度一次巡检，出具巡检报告。\n\n"
            "> 质保期内因设备质量问题产生的维修与更换费用由我方承担。",
         "responds_to": ["r5"]},
    ],
    "figures": [
        {"id": "arch", "caption": "系统总体架构", "width": 0.9, "source": {"svg": arch_svg()}},
        {"id": "gantt", "caption": "进度计划横道图", "width": 0.95, "source": {"svg": gantt_svg()}},
    ],
    "tables": [
        {"id": "devices", "caption": "主要设备清单", "columns": ["设备", "型号规格", "数量", "单位"],
         "rows": [["高清摄像机（枪机）", "400 万像素，H.265", 132, "台"], ["高清摄像机（球机）", "400 万像素，23 倍光学变焦", 54, "台"],
                  ["人脸门禁一体机", "双目活体检测", 24, "套"], ["汇聚存储节点", "16 盘位，单盘 16 TB", 6, "台"],
                  ["烟感与水浸探测器", "NB-IoT", 420, "个"]],
         "note": "型号规格为最低配置要求，品牌以深化设计确认为准。"},
        {"id": "staff", "caption": "项目主要人员", "columns": ["岗位", "人数", "资格", "职责"],
         "rows": [["项目经理", 1, "机电工程一级注册建造师", "全面负责"], ["技术负责人", 1, "高级工程师", "方案与技术质量"],
                  ["施工队长", 2, "电工证、高处作业证", "现场施工"], ["调试工程师", 3, "—", "联调与培训"]]},
    ],
}

READING = {"title": "社区读书角运营方案", "sections": [
    {"id": "s1", "heading": "背景", "body": "社区居民希望有一个安静的阅读空间，周末亲子阅读需求尤其集中。"},
    {"id": "s2", "heading": "选址与布置", "body": "选在社区活动中心二层东侧，约 40 平方米。配书架 6 组、阅读桌 4 张、儿童阅读区 1 处。"},
    {"id": "s3", "heading": "预算", "body": "一次性投入约 5000 元，其中书架与桌椅 1200 元、首批图书 3800 元。"},
    {"id": "s4", "heading": "运营", "body": "由志愿者轮值，每周开放 5 天；每月举办一次读书分享会。"},
]}

BRIEF_EN = {"title": "Pilot Results: Smart Water Meters", "subtitle": "Quarterly brief",
            "meta": {"lang": "en", "author": "Operations Team", "date": "2026-09-30", "toc": False},
            "sections": [
                {"id": "summary", "heading": "Summary", "body":
                    "The pilot replaced **1,200 meters** in two districts. Leak alerts reduced average repair time from 9 days to 2 days "
                    "(see [[tab:kpi]]). Details of the rollout are in [[sec:rollout]]."},
                {"id": "rollout", "heading": "Rollout", "body": "Installation ran for six weeks.\n\n[[tab:kpi]]"},
                {"id": "next", "heading": "Next steps", "body": "1. Extend to District 3\n2. Integrate billing\n3. Review vendor SLA"},
            ],
            "tables": [{"id": "kpi", "caption": "Key indicators", "columns": ["Indicator", "Before", "After"],
                        "rows": [["Average repair time (days)", "9", "2"], ["Unbilled water", "14.2%", "9.8%"]]}]}

def _pfig(i, cap, w, h, seed):
    return {"id": i, "caption": cap, "source": {"media_type": "image/png", "base64": b64png(w, h, seed)}}


# 位图样例：3 节 3 张程序生成的小 PNG，其中第一节放 2 张（嵌入副本、图编号、同节多图）
ILLUSTRATED = {"title": "社区活动图文简报", "sections": [
    {"id": "s1", "heading": "现场", "body": "活动当天的两处布置如下。\n\n[[fig:p1]]\n\n[[fig:p2]]"},
    {"id": "s2", "heading": "签到", "body": "签到区见[[fig:p3]]。\n\n[[fig:p3]]"},
    {"id": "s3", "heading": "小结", "body": "整体顺利，布置见[[fig:p1]]。"},
], "figures": [_pfig("p1", "入口布置", 48, 32, 1), _pfig("p2", "展板", 32, 48, 2), _pfig("p3", "签到台", 40, 40, 3)]}

for name, doc in (("bid_tech", BID), ("reading_corner", READING), ("brief_en", BRIEF_EN), ("illustrated", ILLUSTRATED)):
    (ROOT / "samples" / f"{name}.json").write_text(json.dumps(doc, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
print("ok")
