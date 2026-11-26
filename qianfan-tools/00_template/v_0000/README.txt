视频目录固定文件说明（文件名不要改，脚本按固定名读取）

video.mp4          必需。视频文件，扩展名也可以是 .mov/.avi/.mkv/.webm/.flv/.m4v。
cover.jpg          必需。封面原图。脚本会在本地裁成 4:3 / 16:9 / 3:4 / 9:16 四种比例后上传。
                   若已自行裁好，可改用 cover_4x3.jpg / cover_16x9.jpg / cover_3x4.jpg / cover_9x16.jpg。
title.txt          必需。标题，一行，不要加引号。
description.txt    描述，可多行。
tags.txt           标签，每行一个；“#”前缀会自动去掉。默认：#AI动画 / #古风 / #萌娃
activities.json    官方活动，字符串数组，最多 5 个，填 activity_name，不是 ID。默认空：[]。例：["活动A", "活动B"]
hotspot.json       关联热点，对象或 null。默认空：null。至少含 word 字段，其余字段原样保存。例：{"word":"热点词","hot_value":123}
declaration.json   自主声明。默认：{"aiContent":"内容由AI生成","isOriginal":false}

manifest.json      由脚本生成，记录上传结果，不要手改。
