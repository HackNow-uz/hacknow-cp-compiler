"""Code execution via nsjail sandbox."""

import logging
from app.languages import get_language
from app.sandbox import nsjail_runner, ExecutionResult
from app.schemas.responses import RunResponse, ExecutionStatus

logger = logging.getLogger(__name__)


async def execute_code(
    language_id: str,
    source_code: str,
    input_data: str,
    time_limit_ms: int,
    memory_limit_mb: int,
) -> RunResponse:
    """Compile and execute code in an nsjail sandbox."""

    language = get_language(language_id)
    if not language:
        return RunResponse(status=ExecutionStatus.IE, stderr=f"Unsupported language: {language_id}")

    if not source_code.strip():
        return RunResponse(status=ExecutionStatus.CE, compile_output="Source code is empty")

    logger.info("Execute: lang=%s, limits=%dms/%dMB", language_id, time_limit_ms, memory_limit_mb)

    try:
        result, compile_output, compile_time = await nsjail_runner.execute(
            language=language,
            source_code=source_code,
            input_data=input_data,
            time_limit_ms=time_limit_ms,
            memory_limit_mb=memory_limit_mb,
        )

        status = _determine_status(result, time_limit_ms)

        return RunResponse(
            status=status,
            stdout=result.stdout,
            stderr=result.stderr,
            compile_output=compile_output,
            exit_code=result.exit_code,
            time_ms=result.time_ms,
            memory_kb=result.memory_kb,
            compile_time_ms=compile_time,
        )

    except Exception as e:
        logger.exception("Execution failed: %s", e)
        return RunResponse(status=ExecutionStatus.IE, stderr=str(e))


def _determine_status(result: ExecutionResult, time_limit_ms: int) -> ExecutionStatus:
    if result.output_limit_exceeded: return ExecutionStatus.OLE
    if result.timed_out or result.time_ms > time_limit_ms: return ExecutionStatus.TLE
    if result.memory_exceeded: return ExecutionStatus.MLE
    if result.exit_code != 0: return ExecutionStatus.RTE
    return ExecutionStatus.OK
