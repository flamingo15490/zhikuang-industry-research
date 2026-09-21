# 本地数据目录

本仓库不分发第三方原始数据或授权状态未确认的缓存。运行完整研究界面时，请在本目录准备自己有权使用的数据。

项目当前会读取的主要路径包括：

```text
data/company_profile_summary.parquet   公司名称与代码索引
data/company_profile/                  主营构成缓存
data/profit_analysis/                  完整利润表缓存
data/scoring/current.json              当前五维评分快照
data/scoring/batches/                  历史评分观察批次
data/wind_import/                      可选的本地 Wind 派生结果
```

不同工具还可能需要金属价格、宏观、行情和经营披露缓存。缺失数据应在界面中标为暂缺，不应以零值或其他期间数据代替。

Wind 原始导出文件放在仓库根目录时会被 `.gitignore` 排除。运行本地导入示例：

```powershell
python wind_local.py --market sheet1.csv --financial sheet2.xlsx
```

导入模块只保存可推导字段和校验状态，不复制原始工作表，也不会把补充数据发送给大模型。
