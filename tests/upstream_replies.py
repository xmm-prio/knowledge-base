"""Answers the installed binary really gave, kept verbatim to test the readers against.

Every payload below was captured from codebase-memory-mcp on the deployment host, against a
real repository, and trimmed only by dropping rows -- never by tidying a shape. The readers
were previously written against payloads we had imagined, which is how the gateway shipped a
search that could not read a single result: the shape it expected did not exist.

Re-capture these when the upstream is upgraded, alongside `upstream_schema`. See ADR-0008.
"""

from __future__ import annotations

INDEX_STATUS = {
    "project": "home-mdc-mops-knowledge-base-codebase-ops-nn",
    "nodes": 274722,
    "edges": 1040109,
    "status": "ready",
    "root_path": "/home/mdc/mops-knowledge-base/codebase/ops-nn",
    "parse_partial": {
        "files": [
            {"path": "activation/bnll/op_graph/bnll_proto.h", "error_ranges": "37-37"},
            {"path": "activation/celu/op_kernel/celu.cpp", "error_ranges": "16-16"},
        ]
    },
}
"""`index_status`. The graph's size and what it could not fully parse come with the state."""

SEARCH_BY_NAME = {
    "total": 5844,
    "count": 3,
    "cols": ["name", "label", "lines", "in", "out"],
    "groups": [
        {
            "qn_prefix": (
                "home-mdc-mops-knowledge-base-codebase-ops-nn.matmul.mat_mul_v3.op_kernel."
                "mat_mul_sc_splitk_kernel_gm_to_l1"
            ),
            "file": "matmul/mat_mul_v3/op_kernel/mat_mul_sc_splitk_kernel_gm_to_l1.h",
            "rows": [["AMatMulB", "Function", "725-788", 1, 1]],
        },
        {
            "qn_prefix": (
                "home-mdc-mops-knowledge-base-codebase-ops-nn.matmul.quant_matmul_reduce_sum."
                "op_kernel.quant_matmul_reduce_sum_common"
            ),
            "file": "matmul/quant_matmul_reduce_sum/op_kernel/quant_matmul_reduce_sum_common.h",
            "rows": [["ASCENDC_QUANT_MATMUL_REDUCE_SUM_COMMON_H", "Macro", "16-17", 0, 0]],
        },
    ],
    "has_more": True,
}
"""`search_graph` with `name_pattern` and `format: json`.

Column-oriented and grouped: a row's own `name` is only its last segment, and the qualified
name to ask with next is the group's `qn_prefix` joined to it.
"""

AMATMULB = (
    "home-mdc-mops-knowledge-base-codebase-ops-nn.matmul.mat_mul_v3.op_kernel."
    "mat_mul_sc_splitk_kernel_gm_to_l1.AMatMulB"
)
"""The first qualified name `SEARCH_BY_NAME` identifies, spelled out."""

SEARCH_BY_KEYWORD = {
    "total": 1104,
    "search_mode": "bm25",
    "cols": ["qn", "label", "file", "lines", "rank"],
    "rows": [
        [
            "home-mdc-mops-knowledge-base-codebase-ops-nn.matmul.quant_batch_matmul_v3."
            "op_kernel.quant_batch_matmul_v3.quant_batch_matmul_v3",
            "Function",
            "matmul/quant_batch_matmul_v3/op_kernel/quant_batch_matmul_v3.cpp",
            "212-572",
            -20.70733688733857,
        ],
        [
            "home-mdc-mops-knowledge-base-codebase-ops-nn.matmul.quant_batch_matmul_v4."
            "op_kernel.quant_batch_matmul_v4.quant_batch_matmul_v4",
            "Function",
            "matmul/quant_batch_matmul_v4/op_kernel/quant_batch_matmul_v4.cpp",
            "45-126",
            -20.70733688733857,
        ],
    ],
    "has_more": True,
}
"""`search_graph` with `query`. The same tool, a different shape: flat rows, whole names."""

NOTHING_MATCHED = {
    "total": 0,
    "count": 0,
    "cols": ["name", "label", "lines", "in", "out"],
    "groups": [],
    "has_more": False,
    "hint": "No nodes match this pattern. Check spelling or try a broader regex.",
}

NO_CALLERS = {
    "function": AMATMULB,
    "direction": "inbound",
    "callers_total": 0,
    "callers": {"cols": ["name", "hop", "strategy", "confidence"], "groups": []},
}
"""`trace_path` with evidence, for a symbol nothing calls."""

TRACED = {
    "function": AMATMULB,
    "direction": "inbound",
    "callers_total": 3,
    "callers": {
        "cols": ["name", "hop", "strategy", "confidence"],
        "groups": [
            {
                "qn_prefix": (
                    "home-mdc-mops-knowledge-base-codebase-ops-nn.matmul.mat_mul_v3.op_kernel."
                    "mat_mul_sc_splitk_kernel"
                ),
                "file": "matmul/mat_mul_v3/op_kernel/mat_mul_sc_splitk_kernel.h",
                "rows": [
                    ["Compute", 1, "lsp", 0.98],
                    ["Process", 2, "lsp", 0.95],
                    ["MaybeCompute", 1, "unresolved", 0.2],
                ],
            }
        ],
    },
}
"""The same, with hops. Note what is absent: the upstream states each hop's distance from
the symbol asked about, never which symbol it arrived through, so only the first hop is an
edge anybody can draw."""

GREP = """results: 2  (cols: qn label file lines matches in out)
  home-mdc-mops-knowledge-base-codebase-ops-nn.conv.convolution_forward.op_host.op_api.\
aclnn_convolution.aclnnConvolutionGetWorkspaceSize Function \
conv/convolution_forward/op_host/op_api/aclnn_convolution.cpp 5384-5464 5411;5415;5418 9 9
  home-mdc-mops-knowledge-base-codebase-ops-nn.common.src.op_host.op_cache_tiling.Ops.NN.\
GenTiling Function common/src/op_host/op_cache_tiling.cpp 54-71 "63" 4 2
raw: 3  (cols: file line content)
  conv/deformable_conv2d/op_kernel/deformable_conv2d_base.h 24 "constexpr MatmulConfig MDL_CFG \
= GetNormalConfig();"
  experimental/matmul/fused_matmul_gelu/op_host/fused_matmul_gelu_tiling.h 19 \
BEGIN_TILING_DATA_DEF(FusedMatmulGeluTilingData)
  experimental/matmul/fused_matmul_gelu/op_api/aclnn_fused_matmul_gelu.h 22 " * @brief \
aclnnFusedMatmulGelu first-stage API."
dirs: 2  (cols: dir hits)
  conv/ 29
  experimental/ 169
total_grep_matches: 500
total_results: 217
raw_match_count: 3
elapsed_ms: 419
"""
"""`search_code`. It takes no `format`, so this is the only shape it has: a text report whose
`results` section is the declarations the matches fall inside and whose `raw` section is the
matching lines. Note one quoted content and one unquoted."""

SNIPPET = {
    "name": "matmul/mat_mul_v3/op_kernel/mat_mul_sc_splitk_kernel_gm_to_l1.h",
    "qualified_name": AMATMULB,
    "label": "Module",
    "file_path": (
        "/home/mdc/mops-knowledge-base/codebase/ops-nn/matmul/mat_mul_v3/op_kernel/"
        "mat_mul_sc_splitk_kernel_gm_to_l1.h"
    ),
    "start_line": 1,
    "end_line": 500,
    "source_clipped": True,
    "clipped_at_lines": 500,
    "source": "/**\n * Copyright (c) 2025 Huawei Technologies Co., Ltd.\n */\n",
}
"""`get_code_snippet`. It clips long bodies and says so, which a reader has to be told."""
