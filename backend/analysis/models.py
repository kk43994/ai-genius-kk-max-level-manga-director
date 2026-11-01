"""LibTV public text model names verified with search_models on 2026-11-01.

Names are provider labels, not claims about unverified upstream vendors.
The exact selected ID is rechecked with get_model before every submission.
"""
DEFAULT_MODEL = 'aurora-3-prime'
MODELS = (
    {'id':'aurora-3-prime','name':'GVLM 3.1','provider':'libtv'},
    {'id':'cvlm-5.5','name':'CVLM 5.5','provider':'libtv'},
    {'id':'aurora-3-lite','name':'GVLM 3.1 Flash','provider':'libtv'},
    {'id':'qwen-3-vl-flash','name':'Qwen 3 VL Flash','provider':'libtv'},
)

def selected_model(model_id):
    from backend.workflow.errors import WorkflowError
    for model in MODELS:
        if model['id'] == model_id:return dict(model)
    raise WorkflowError('ANALYSIS_MODEL_UNAVAILABLE', '所选文本模型尚未接入，请重新选择。', 422)
