let s:job = v:null
let s:python_script = expand('<sfile>:p:h:h:h') . '/python/copylot.py'
let s:history = []
let s:response_buffer = ''
let s:callback_funs = {
    \ 'answer': function('copylot#server#handle_answer'),
    \ 'ends': function('copylot#server#handle_ends'),
    \ 'error': function('copylot#server#handle_error'),
    \ 'gitmsg': function('copylot#git#handle_gitmsg'),
\}
let s:history_limit = get(g:, 'copylot_history', 20)


function! copylot#server#available() abort
    return executable('python3') || executable('python')
endfunction


function! copylot#server#start() abort
    if !copylot#server#available()
        return
    endif

    if s:job != v:null && job_status(s:job) ==# 'run'
        return
    endif

    let l:python = executable('python3') ? 'python3' : 'python'
    let l:cmd = [l:python, s:python_script]
    if exists('g:copylot_config')
        call add(l:cmd, expand(g:copylot_config))
    endif

    let s:job = job_start(l:cmd, {
        \ 'out_mode': 'raw',
        \ 'in_io': 'pipe',
        \ 'out_io': 'pipe',
        \ 'err_io': 'pipe',
        \ 'out_cb': function('s:on_response'),
        \ 'exit_cb': function('s:on_exit'),
        \ })
endfunction


function! copylot#server#stop() abort
    if s:job != v:null && job_status(s:job) ==# 'run'
        call job_stop(s:job)
        let s:job = v:null
        let s:channel = v:null
    endif
endfunction


function! copylot#server#query(question) abort
    if s:job == v:null || job_status(s:job) !=# 'run'
        call copylot#chat#print('__[Error]__: Server is ' . (s:job == v:null ? 'not running' : job_status(s:job)), 1)
        return
    endif

    call add(s:history, {'role': 'user', 'content': a:question})
    if len(s:history) > s:history_limit
        call remove(s:history, 0)
    endif

    " Detect @agent at the start (ignoring leading spaces, followed by space or newline)
    let l:action = 'query'
    let l:lines = split(a:question, "\n")
    let l:first_line = empty(l:lines) ? '' : l:lines[0]
    if l:first_line =~? '^\s*@clear\($\|\s\)'
        call copylot#chat#reset()
        let s:history = []
        let l:rest = matchstr(a:question, '^\s*\c@clear\_s*\zs\_.*')
        if !empty(l:rest)
            call copylot#chat#print("> _Question_:\n", 1)
            call copylot#chat#print(l:rest, 0)
            call copylot#chat#print("\n> _Answer_:\n", 1)
            call copylot#server#query(l:rest)
        endif
        return
    elseif l:first_line =~? '^\s*@agent\($\|\s\)'
        let l:action = 'agent'
    endif

    let l:data = {
        \ 'action': l:action,
        \ 'content': s:history,
    \}
    call s:send(l:data)
endfunction


function! copylot#server#action(data) abort
    call s:send(a:data)
endfunction


function! s:send(data) abort
    if s:job == v:null || job_status(s:job) !=# 'run'
        return
    endif

    let l:json_req = json_encode(a:data)
    call ch_sendraw(s:job, l:json_req . "\n\n")
endfunction


function! s:on_response(channel, msg) abort
    if empty(a:msg)
        return
    endif

    let s:response_buffer .= a:msg
    while stridx(s:response_buffer, "\n\n") >= 0
        let l:pos = stridx(s:response_buffer, "\n\n")
        let l:response_json = s:response_buffer[:l:pos-1]
        let s:response_buffer = s:response_buffer[l:pos+2:]

        if empty(l:response_json)
            continue
        endif

        let l:response_data = json_decode(l:response_json)
        if has_key(l:response_data, 'type') && has_key(s:callback_funs, l:response_data.type)
            call call(s:callback_funs[l:response_data.type], [l:response_data])
        endif
    endwhile
endfunction


function! s:on_exit(channel, exit_code) abort
    if a:exit_code != 0
        echomsg "Copylot Server Exit Faultly"
    endif
    let s:job = v:null
    let s:response_buffer = ''
endfunction


function! copylot#server#handle_answer(response) abort
    let l:msg = get(a:response, 'content', '')
    if type(l:msg) != v:t_string
        let l:msg = string(l:msg)
    endif

    if empty(s:history) || s:history[-1].role !=# 'assistant'
        call add(s:history, {'role': 'assistant', 'content': l:msg})
    else
        if type(s:history[-1].content) != v:t_string
            let s:history[-1].content = string(s:history[-1].content)
        endif
        let s:history[-1].content .= l:msg
    endif

    call copylot#chat#print(l:msg)
endfunction


function! copylot#server#handle_ends(response) abort
    call copylot#chat#print('————————————', 1)
    call copylot#chat#switch('show')
    call copylot#chat#addButtons()
endfunction


function! copylot#server#handle_error(response) abort
    let l:error_msg = get(a:response, 'content', 'Unknown error')
    call copylot#chat#print('__[Error]__: ' . l:error_msg, 1)
    call copylot#chat#print('————————————', 1)
    call copylot#chat#switch('show')
    call copylot#chat#addButtons()
endfunction