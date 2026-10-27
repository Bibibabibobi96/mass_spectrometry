# pulse-resolution candidate r02 promotion receipt封存

DOC_STATUS: ARCHIVED_READ_ONLY

`pulse_resolution_direct_candidates_v5_r02`的sequence 2完成N=100 Fly、分析、candidate result receipt与parent
publication；frontend/overlay cache均命中，handoff/detector=`62/52`。candidate result为单峰，
`R=4343.205166436997`、direct TOF FWHM=`3.5886389419879094 ns`，paired promotion decision为`reject`。

candidate result receipt self-SHA验证通过，但promotion gate先计算self-SHA，registrar随后追加
`baseline_result_sha256`和`candidate_result_sha256`，使已发布promotion receipt的claimed self-SHA不再覆盖
最终全部字段。r02停止复用；parent manifest SHA-256为
`1EA08757F73007254559AA68BFB1FFFCE10F2E5B043E71CC8C7C05B46CCF66AA`。

最小修复不改变promotion算法或物理结果：移除gate返回的旧self-SHA，写完两个结果绑定SHA后，最后用既有
canonical JSON SHA函数重算self-SHA，随后不再修改receipt。successor r03只改变campaign/run身份及由run
身份派生的experiment-row SHA；源、场、几何、时钟、r09 baseline、数值设置和执行顺序不变。
