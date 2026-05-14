# Local Relay Tool Usage Summary

- Evidence root: `/Users/user/.rig/relay`
- Files scanned: `16658`
- Parseable records: `74610`
- Tool/event records: `14719`
- Malformed records: `0`

## Top Tools by Usage
- `bash`: `count` `5023` failures `337` tier `3`
- `read_file`: `count` `3970` failures `14` tier `1`
- `search_replace`: `count` `2057` failures `217` tier `1`
- `grep`: `count` `1243` failures `4` tier `0`
- `write_file`: `count` `943` failures `39` tier `2`
- `git_status`: `count` `400` failures `0` tier `4`
- `tool_output_written`: `count` `378` failures `0` tier `0`
- `coordination`: `count` `260` failures `28` tier `0`
- `todo`: `count` `238` failures `0` tier `0`
- `git_diff`: `count` `54` failures `0` tier `4`

## Top Tools by Failure
- `bash`: `failure_count` `337` failures `337` tier `3`
- `search_replace`: `failure_count` `217` failures `217` tier `1`
- `write_file`: `failure_count` `39` failures `39` tier `2`
- `coordination`: `failure_count` `28` failures `28` tier `0`
- `read_file`: `failure_count` `14` failures `14` tier `1`
- `web_fetch`: `failure_count` `4` failures `4` tier `0`
- `grep`: `failure_count` `4` failures `4` tier `0`
- `task`: `failure_count` `2` failures `2` tier `0`
- `ask_user_question`: `failure_count` `0` failures `0` tier `0`
- `checkpoint`: `failure_count` `0` failures `0` tier `4`

## Top Tools by Latency
- `ask_user_question`: `p95_latency_ms` `356811` failures `0` tier `0`
- `task`: `p95_latency_ms` `288279` failures `2` tier `0`
- `bash`: `p95_latency_ms` `10469` failures `337` tier `3`
- `read_file`: `p95_latency_ms` `1702` failures `14` tier `1`
- `git_status`: `p95_latency_ms` `858` failures `0` tier `4`
- `checkpoint`: `p95_latency_ms` `658` failures `0` tier `4`
- `write_file`: `p95_latency_ms` `631` failures `39` tier `2`
- `search_replace`: `p95_latency_ms` `506` failures `217` tier `1`
- `web_fetch`: `p95_latency_ms` `498` failures `4` tier `0`
- `git_log`: `p95_latency_ms` `270` failures `0` tier `4`

## Top Tools by Output Size
- `coordination`: `p95_output_bytes` `429835` failures `28` tier `0`
- `web_fetch`: `p95_output_bytes` `73233` failures `4` tier `0`
- `git_ls_files`: `p95_output_bytes` `64140` failures `0` tier `4`
- `git_show`: `p95_output_bytes` `64127` failures `0` tier `4`
- `search_replace`: `p95_output_bytes` `31470` failures `217` tier `1`
- `git_status`: `p95_output_bytes` `27601` failures `0` tier `4`
- `read_file`: `p95_output_bytes` `18867` failures `14` tier `1`
- `write_file`: `p95_output_bytes` `18666` failures `39` tier `2`
- `task`: `p95_output_bytes` `13265` failures `2` tier `0`
- `bash`: `p95_output_bytes` `8012` failures `337` tier `3`

## Hardening Priorities
- `bash` tier `3` count `5023` failures `337`
- `search_replace` tier `1` count `2057` failures `217`
- `write_file` tier `2` count `943` failures `39`
- `coordination` tier `0` count `260` failures `28`
- `read_file` tier `1` count `3970` failures `14`
- `grep` tier `0` count `1243` failures `4`
- `web_fetch` tier `0` count `40` failures `4`
- `task` tier `0` count `15` failures `2`
