"""Cashier-only break area. No POS database writes or network calls."""
import random
import streamlit as st

SURAHS = {
    'الفاتحة': 'بِسْمِ اللَّهِ الرَّحْمَٰنِ الرَّحِيمِ ۝ الْحَمْدُ لِلَّهِ رَبِّ الْعَالَمِينَ ۝ الرَّحْمَٰنِ الرَّحِيمِ ۝ مَالِكِ يَوْمِ الدِّينِ ۝ إِيَّاكَ نَعْبُدُ وَإِيَّاكَ نَسْتَعِينُ ۝ اهْدِنَا الصِّرَاطَ الْمُسْتَقِيمَ ۝ صِرَاطَ الَّذِينَ أَنْعَمْتَ عَلَيْهِمْ غَيْرِ الْمَغْضُوبِ عَلَيْهِمْ وَلَا الضَّالِّينَ',
    'الإخلاص': 'بِسْمِ اللَّهِ الرَّحْمَٰنِ الرَّحِيمِ ۝ قُلْ هُوَ اللَّهُ أَحَدٌ ۝ اللَّهُ الصَّمَدُ ۝ لَمْ يَلِدْ وَلَمْ يُولَدْ ۝ وَلَمْ يَكُنْ لَهُ كُفُوًا أَحَدٌ',
    'الفلق': 'بِسْمِ اللَّهِ الرَّحْمَٰنِ الرَّحِيمِ ۝ قُلْ أَعُوذُ بِرَبِّ الْفَلَقِ ۝ مِنْ شَرِّ مَا خَلَقَ ۝ وَمِنْ شَرِّ غَاسِقٍ إِذَا وَقَبَ ۝ وَمِنْ شَرِّ النَّفَّاثَاتِ فِي الْعُقَدِ ۝ وَمِنْ شَرِّ حَاسِدٍ إِذَا حَسَدَ',
    'الناس': 'بِسْمِ اللَّهِ الرَّحْمَٰنِ الرَّحِيمِ ۝ قُلْ أَعُوذُ بِرَبِّ النَّاسِ ۝ مَلِكِ النَّاسِ ۝ إِلَٰهِ النَّاسِ ۝ مِنْ شَرِّ الْوَسْوَاسِ الْخَنَّاسِ ۝ الَّذِي يُوَسْوِسُ فِي صُدُورِ النَّاسِ ۝ مِنَ الْجِنَّةِ وَالنَّاسِ',
}

def _css():
    st.markdown('''<style>
    .stApp {background:radial-gradient(ellipse at 20% 10%,#39210f,#110b09 70%) !important;}
    [data-testid="stHeader"],[data-testid="stSidebar"],[data-testid="stSidebarCollapsedControl"] {display:none !important;}
    [data-testid="stMainBlockContainer"] {max-width:1040px !important;padding:1rem 1.5rem 3rem !important;}
    [data-testid="stToolbar"], [data-testid="stDecoration"] {display:none !important;}
    [data-testid="stMain"] {overflow-y:auto !important;}
    .break-head {text-align:center;border:1px solid #ad803a;border-radius:20px;padding:26px;background:#21150f;box-shadow:0 10px 32px #0007;}
    .break-head h1 {color:#f5ca7e !important;font-size:clamp(27px,4vw,45px) !important;}
    .break-head p,.break-head small {color:#eed6ad !important;}
    [data-testid="stMain"] p,[data-testid="stMain"] label,[data-testid="stMain"] h3 {color:#f1d6a9 !important;}
    [data-testid="stMain"] div.stButton button {background:linear-gradient(120deg,#a46c27,#e4b864) !important;color:#211208 !important;border-radius:12px;}
    </style>''', unsafe_allow_html=True)

def _unlock():
    st.subheader('🔒 العودة للعمل')
    st.caption('لأمان المبيعات، لازم نفس الكاشير يدخل كلمة مروره قبل الرجوع.')
    with st.form('break_unlock_form', clear_on_submit=True):
        password = st.text_input('كلمة مرور الكاشير', type='password')
        submit = st.form_submit_button('🔓 فتح شاشة الكاشير', use_container_width=True)
    if submit:
        try:
            from branch_auth import local_login
            user = local_login(st.session_state.get('username', ''), password)
            if (user and str(user.get('id')) == str(st.session_state.get('user_id'))
                    and user.get('role') == 'Cashier'):
                st.session_state['cashier_break_locked'] = False
                st.session_state.pop('break_show_unlock', None)
                st.session_state['pos_focus_barcode'] = True
                st.rerun()
            st.error('كلمة المرور غير صحيحة أو الحساب غير مطابق.')
        except Exception:
            st.error('تعذر التحقق محليًا من كلمة المرور. الاستراحة ستظل مقفولة.')

def _ttt():
    st.subheader('⭕ إكس أو — لاعب ضد الكمبيوتر')
    board = st.session_state.setdefault('break_ttt', [''] * 9)
    def winner(b):
        for a,c,d in ((0,1,2),(3,4,5),(6,7,8),(0,3,6),(1,4,7),(2,5,8),(0,4,8),(2,4,6)):
            if b[a] and b[a] == b[c] == b[d]: return b[a]
        return 'تعادل' if all(b) else ''
    result = winner(board)
    for r in range(3):
        cols = st.columns(3)
        for c in range(3):
            i = r*3+c
            if cols[c].button(board[i] or '·',key=f'break_ttt_{i}',disabled=bool(board[i] or result),use_container_width=True):
                board[i]='❌'
                if not winner(board):
                    empties=[j for j,v in enumerate(board) if not v]
                    if empties: board[random.choice(empties)]='⭕'
                st.rerun()
    result=winner(board)
    if result: st.info('النتيجة: '+result)
    if st.button('🔄 لعبة جديدة',key='break_ttt_reset'):
        st.session_state['break_ttt']=['']*9
        st.rerun()

def _memory():
    st.subheader('🧠 تحدي الذاكرة')
    if 'break_memory_target' not in st.session_state:
        st.session_state['break_memory_target'] = random.randint(1000,9999)
        st.session_state['break_memory_phase'] = 'show'
    if st.session_state['break_memory_phase']=='show':
        st.metric('احفظ الرقم',str(st.session_state['break_memory_target']))
        if st.button('حفظت الرقم — اختبرني'):
            st.session_state['break_memory_phase']='guess'
            st.rerun()
    else:
        guess=st.text_input('اكتب الرقم الذي حفظته',key='break_memory_guess')
        if st.button('تحقق'):
            st.success('ممتاز! 👏' if guess==str(st.session_state['break_memory_target']) else 'حاول مرة أخرى 🌟') if guess==str(st.session_state['break_memory_target']) else st.warning('الرقم الصحيح: '+str(st.session_state['break_memory_target']))
        if st.button('رقم جديد'):
            st.session_state['break_memory_target']=random.randint(1000,9999)
            st.session_state['break_memory_phase']='show'
            st.rerun()

def _sudoku():
    st.subheader('🔢 سودوكو مصغّرة — 4 × 4')
    st.caption('املأ الأرقام من 1 إلى 4 بحيث لا يتكرر رقم في الصف أو العمود أو المربع 2×2.')
    puzzles = [
        ([[1,0,0,4],[0,4,1,0],[2,0,4,0],[0,3,0,1]], [[1,2,3,4],[3,4,1,2],[2,1,4,3],[4,3,2,1]]),
        ([[0,2,0,4],[3,0,1,0],[0,1,0,3],[4,0,2,0]], [[1,2,3,4],[3,4,1,2],[2,1,4,3],[4,3,2,1]]),
    ]
    idx = st.session_state.setdefault('break_sudoku_idx', 0)
    puzzle, solution = puzzles[idx % len(puzzles)]
    with st.form('break_sudoku_form'):
        guesses = []
        for r in range(4):
            cols = st.columns(4)
            row = []
            for c in range(4):
                if puzzle[r][c]:
                    cols[c].markdown(f'**{puzzle[r][c]}**')
                    row.append(puzzle[r][c])
                else:
                    row.append(cols[c].selectbox(f'صف {r+1} عمود {c+1}', [0,1,2,3,4],
                                                format_func=lambda x: '—' if x == 0 else str(x),
                                                key=f'break_sudoku_{idx}_{r}_{c}', label_visibility='collapsed'))
            guesses.append(row)
        check = st.form_submit_button('✔️ تحقق من الحل')
    if check:
        if guesses == solution:
            st.success('أحسنت! الحل صحيح 🎉')
        else:
            st.warning('لسه فيه خانات ناقصة أو أرقام غير صحيحة. حاول تاني.')
    if st.button('🆕 لغز جديد', key='break_sudoku_new'):
        st.session_state['break_sudoku_idx'] = idx + 1
        st.rerun()


def _words():
    st.subheader('🔤 ترتيب الكلمات')
    words = [('قهوة', 'مشروب تشتهر به المحامص'), ('فستق', 'نوع من المكسرات'),
             ('لوز', 'نوع من المكسرات'), ('تمر', 'فاكهة معروفة'),
             ('كاجو', 'نوع من المكسرات')]
    idx = st.session_state.setdefault('break_word_idx', 0)
    answer, hint = words[idx % len(words)]
    rng = random.Random(idx + 1307)
    letters = list(answer)
    rng.shuffle(letters)
    st.info('الحروف: ' + '  |  '.join(letters))
    st.caption('تلميح: ' + hint)
    with st.form('break_word_form', clear_on_submit=True):
        guess = st.text_input('اكتب الكلمة الصحيحة')
        submit = st.form_submit_button('تحقق')
    if submit:
        if guess.strip() == answer:
            st.success('إجابة صحيحة! 👏')
        else:
            st.warning('حاول مرة ثانية')
    if st.button('الكلمة التالية', key='break_word_next'):
        st.session_state['break_word_idx'] = idx + 1
        st.rerun()


from pathlib import Path
import json
import html

# Assets are optional and are deliberately outside the POS database.
_BREAK_ASSETS = Path(__file__).resolve().parent / 'cashier_break_assets'

def _load_quran():
    """Read a locally provided, verified JSON corpus; never generate sacred text."""
    path = _BREAK_ASSETS / 'quran.json'
    if not path.is_file():
        return None, 'ملف المصحف الكامل غير موجود. ضع نسخة JSON موثوقة ومراجعة في views/cashier_break_assets/quran.json.'
    try:
        data = json.loads(path.read_text(encoding='utf-8-sig'))
        if isinstance(data, dict) and 'surahs' in data:
            data = data['surahs']
        if not isinstance(data, list) or len(data) != 114:
            raise ValueError('عدد السور يجب أن يكون 114')
        normalized=[]
        for index, surah in enumerate(data, 1):
            if not isinstance(surah, dict): raise ValueError('بنية السور غير صحيحة')
            number = int(surah.get('number', index))
            name = str(surah.get('name', '')).strip()
            ayahs = surah.get('ayahs', surah.get('verses'))
            if number != index or not name or not isinstance(ayahs,list) or not ayahs:
                raise ValueError('سورة غير مكتملة: '+str(index))
            texts=[]
            for a in ayahs:
                value = a.get('text', '') if isinstance(a,dict) else a
                if not isinstance(value,str) or not value.strip(): raise ValueError('آية فارغة')
                texts.append(value.strip())
            normalized.append((name,texts))
        return normalized, None
    except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
        return None, 'تعذر قراءة ملف المصحف: '+str(exc)

def _quran_full():
    st.subheader('📖 المصحف الكريم')
    data,error=_load_quran()
    if error:
        st.warning(error)
        st.caption('إلى أن تضيف المصحف الكامل، يمكنك قراءة السور الأربع الموجودة في النسخة السابقة.')
        surah=st.selectbox('اختر السورة', list(SURAHS), key='break_short_surah')
        st.markdown('<div style="direction:rtl;text-align:center;font-size:24px;line-height:2.5;color:#f4d6a1;background:#241710;padding:24px;border-radius:18px">'+html.escape(SURAHS[surah])+'</div>', unsafe_allow_html=True)
        return
    query=st.text_input('🔎 بحث باسم السورة',key='break_quran_search')
    choices=[(i,name) for i,(name,_) in enumerate(data,1) if query.strip() in name]
    if not choices:
        st.info('لا توجد سورة بهذا الاسم.')
        return
    chosen=st.selectbox('اختر السورة', choices, format_func=lambda x: f'{x[0]} - {x[1]}',key='break_full_surah')
    verses=data[chosen[0]-1][1]
    st.markdown('<div style="direction:rtl;text-align:center;font-size:23px;line-height:2.6;color:#f4d6a1;background:#241710;padding:24px;border-radius:18px">'+ ' ۞ '.join(html.escape(v) for v in verses)+'</div>',unsafe_allow_html=True)
    audio_dir=_BREAK_ASSETS/'audio'
    for suffix in ('.mp3','.ogg','.wav'):
        audio_path=audio_dir/(f'{chosen[0]:03d}'+suffix)
        if audio_path.is_file():
            st.audio(str(audio_path));break
    else:
        st.caption('للاستماع بدون إنترنت، ضع ملف التلاوة باسم رقم السورة، مثل 001.mp3، داخل cashier_break_assets/audio.')

def _chess_initial():
    return [list('rnbqkbnr'),list('pppppppp'),list('........'),list('........'),list('........'),list('........'),list('PPPPPPPP'),list('RNBQKBNR')]

def _chess_owner(p):
    if p=='.':return None
    return 'w' if p.isupper() else 'b'

def _chess_moves(b,r,c,attacks=False):
    p=b[r][c]
    if p=='.':return []
    side=_chess_owner(p); kind=p.lower(); result=[]
    def add(rr,cc):
        if 0<=rr<8 and 0<=cc<8 and (attacks or _chess_owner(b[rr][cc])!=side):
            if attacks or b[rr][cc]=='.' or b[rr][cc].lower()!='k': result.append((rr,cc))
    if kind=='p':
        d=-1 if side=='w' else 1
        if attacks:
            for dc in (-1,1):add(r+d,c+dc)
        else:
            if 0<=r+d<8 and b[r+d][c]=='.':
                add(r+d,c)
                if r==(6 if side=='w' else 1) and b[r+2*d][c]=='.':add(r+2*d,c)
            for dc in (-1,1):
                rr,cc=r+d,c+dc
                if 0<=rr<8 and 0<=cc<8 and b[rr][cc]!='.' and _chess_owner(b[rr][cc])!=side:add(rr,cc)
    elif kind=='n':
        for dr,dc in ((-2,-1),(-2,1),(2,-1),(2,1),(-1,-2),(-1,2),(1,-2),(1,2)):add(r+dr,c+dc)
    elif kind=='k':
        for dr in (-1,0,1):
            for dc in (-1,0,1):
                if dr or dc:add(r+dr,c+dc)
    else:
        dirs=[]
        if kind in ('r','q'):dirs += [(1,0),(-1,0),(0,1),(0,-1)]
        if kind in ('b','q'):dirs += [(1,1),(1,-1),(-1,1),(-1,-1)]
        for dr,dc in dirs:
            rr,cc=r+dr,c+dc
            while 0<=rr<8 and 0<=cc<8:
                if b[rr][cc]=='.':result.append((rr,cc))
                else:
                    if _chess_owner(b[rr][cc])!=side and (attacks or b[rr][cc].lower()!='k'):result.append((rr,cc))
                    break
                rr+=dr;cc+=dc
    return result

def _chess_check(b,side):
    king='K' if side=='w' else 'k'
    kings=[(r,c) for r in range(8) for c in range(8) if b[r][c]==king]
    if len(kings)!=1:return True
    square=kings[0]
    return any(square in _chess_moves(b,r,c,attacks=True) for r in range(8) for c in range(8) if b[r][c]!='.' and _chess_owner(b[r][c])!=side)

def _chess_apply(b, side, src, dst, ep=None, castle=None, promotion='q'):
    """Return a new board after a move, including special moves."""
    r,c=src; rr,cc=dst
    new=[row[:] for row in b]
    piece=new[r][c]
    new[r][c]='.'
    if piece.lower()=='p' and c!=cc and new[rr][cc]=='.' and ep==(rr,cc):
        new[r][cc]='.'  # en passant: captured pawn is on source rank
    new[rr][cc]=piece
    if piece.lower()=='k' and abs(cc-c)==2:
        if cc==6:
            new[r][5]=new[r][7];new[r][7]='.'
        elif cc==2:
            new[r][3]=new[r][0];new[r][0]='.'
    if piece=='P' and rr==0:new[rr][cc]=promotion.upper()
    if piece=='p' and rr==7:new[rr][cc]=promotion.lower()
    return new


def _chess_legal(b,side,r,c,ep=None,rights=None):
    if _chess_owner(b[r][c])!=side:return []
    rights=rights or set()
    piece=b[r][c]
    moves=list(_chess_moves(b,r,c))
    if piece.lower()=='p' and ep is not None:
        er,ec=ep
        d=-1 if side=='w' else 1
        if er==r+d and abs(ec-c)==1 and b[er][ec]=='.' and b[r][ec]==('p' if side=='w' else 'P'):
            moves.append((er,ec))
    if piece.lower()=='k' and not _chess_check(b,side):
        home=7 if side=='w' else 0
        if r==home and c==4:
            for letter,rook_col,empty,transit,dst in (
                ('K' if side=='w' else 'k',7,(5,6),5,6),
                ('Q' if side=='w' else 'q',0,(1,2,3),3,2),
            ):
                rook='R' if side=='w' else 'r'
                if letter in rights and b[home][rook_col]==rook and all(b[home][x]=='.' for x in empty):
                    # King cannot pass through check.
                    mid=_chess_apply(b,side,(r,c),(home,transit))
                    if not _chess_check(mid,side):moves.append((home,dst))
    legal=[]
    for rr,cc in moves:
        new=_chess_apply(b,side,(r,c),(rr,cc),ep)
        if not _chess_check(new,side):legal.append((rr,cc))
    return legal


def _chess():
    st.subheader('♟️ شطرنج — لاعبان على نفس الجهاز')
    st.caption('شطرنج محلي دون إنترنت: الشاه وكش مات والتبييت والأخذ بالتجاوز وترقية البيدق إلى وزير.')
    b=st.session_state.setdefault('break_chess_board',_chess_initial())
    side=st.session_state.setdefault('break_chess_side','w')
    rights=st.session_state.setdefault('break_chess_rights',set('KQkq'))
    ep=st.session_state.get('break_chess_ep')
    selected=st.session_state.get('break_chess_selected')
    all_moves=[(r,c,rr,cc) for r in range(8) for c in range(8) if _chess_owner(b[r][c])==side for rr,cc in _chess_legal(b,side,r,c,ep,rights)]
    if not all_moves:
        st.error('كش مات — انتهت اللعبة' if _chess_check(b,side) else 'تعادل — لا توجد حركات قانونية')
    else:
        st.info(('دور الأبيض' if side=='w' else 'دور الأسود')+(' — الملك في كش!' if _chess_check(b,side) else ''))
    symbols={'K':'♔','Q':'♕','R':'♖','B':'♗','N':'♘','P':'♙','k':'♚','q':'♛','r':'♜','b':'♝','n':'♞','p':'♟','.' :'·'}
    possible=_chess_legal(b,side,*selected,ep,rights) if selected else []
    for r in range(8):
        cols=st.columns(8,gap='small')
        for c in range(8):
            icon=symbols[b[r][c]]
            marker='🟨' if selected==(r,c) else '🟢' if (r,c) in possible else ('⬜' if (r+c)%2 else '🟫')
            if cols[c].button(marker+icon,key=f'break_chess_{r}_{c}',use_container_width=True,disabled=not bool(all_moves)):
                if selected and (r,c) in possible:
                    sr,sc=selected
                    piece=b[sr][sc]
                    captured=b[r][c]
                    next_rights=set(rights)
                    if piece=='K':next_rights.difference_update('KQ')
                    if piece=='k':next_rights.difference_update('kq')
                    for sq,flag in [((7,0),'Q'),((7,7),'K'),((0,0),'q'),((0,7),'k')]:
                        if (sr,sc)==sq or (r,c)==sq:next_rights.discard(flag)
                    st.session_state['break_chess_board']=_chess_apply(b,side,(sr,sc),(r,c),ep)
                    st.session_state['break_chess_rights']=next_rights
                    st.session_state['break_chess_ep']=((r+sr)//2,c) if piece.lower()=='p' and abs(r-sr)==2 else None
                    st.session_state['break_chess_side']='b' if side=='w' else 'w'
                    st.session_state['break_chess_selected']=None
                else:
                    st.session_state['break_chess_selected']=(r,c) if _chess_owner(b[r][c])==side else None
                st.rerun()
    if st.button('🔄 بدء مباراة جديدة',key='break_chess_reset'):
        st.session_state['break_chess_board']=_chess_initial()
        st.session_state['break_chess_side']='w'
        st.session_state['break_chess_selected']=None
        st.session_state['break_chess_rights']=set('KQkq')
        st.session_state['break_chess_ep']=None
        st.rerun()


def _chess_notice():
    st.subheader('♟️ الشطرنج')
    st.info('الشطرنج الكامل يحتاج محرك لعب وواجهة مستقلة؛ لم نضفه في هذه النسخة حتى لا نعرض لعبة غير مكتملة.')

def show():
    if st.session_state.get('role') != 'Cashier' or not st.session_state.get('logged_in'):
        st.error('هذه الاستراحة متاحة للكاشير فقط.')
        st.stop()
    _css()
    st.markdown('<div class="break-head"><h1>☕ استراحة شريف</h1><p>وقت راحة لطيف — شاشة البيع مؤمّنة</p><small>لا يتم إغلاق الوردية أو حذف السلة</small></div>',unsafe_allow_html=True)
    st.write('')
    if st.button('🔐 العودة للكاشير — إدخال كلمة المرور', key='break_back_top', use_container_width=True):
        st.session_state['break_show_unlock'] = True
        st.rerun()
    if st.session_state.get('break_show_unlock'):
        _unlock()
        st.divider()
    tab1,tab2=st.tabs(['📖 القرآن والأذكار','🎮 الألعاب'])
    with tab1:
        _quran_full()
        st.info('أذكار قصيرة: سُبْحَانَ اللَّهِ — الْحَمْدُ لِلَّهِ — اللَّهُ أَكْبَرُ — أَسْتَغْفِرُ اللَّهَ')
        st.caption('المصحف الكامل والتلاوات يُقرآن من ملفات محلية بعد توفيرها والتحقق من مصدرها.')
    with tab2:
        game=st.radio('اختر اللعبة',['إكس أو','تحدي الذاكرة','سودوكو','ترتيب الكلمات','الشطرنج'],horizontal=True)
        if game=='إكس أو': _ttt()
        elif game=='تحدي الذاكرة': _memory()
        elif game=='سودوكو': _sudoku()
        elif game=='ترتيب الكلمات': _words()
        else: _chess()
    st.stop()
