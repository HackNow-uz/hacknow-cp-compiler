"""Per-language source programs that provoke each verdict.

One dict per language id. Every program reads two ints from stdin and is
expected to print their sum, except where the verdict requires otherwise.
This is the ground truth for the Phase 1 verdict matrix: 17 languages x the
verdicts each can reach.

Keys:
  ok    -> prints a+b                     -> OK
  wa    -> prints a wrong number          -> WA
  ce    -> does not compile/parse         -> CE  (None for interpreted-only langs
                                                  where the runtime has no compile step)
  rte   -> exits non-zero / throws        -> RTE
  tle   -> busy loop                      -> TLE
  mle   -> allocates far past the limit   -> MLE
  ole   -> floods stdout past 16 MB       -> OLE
"""

PROGRAMS = {
    "c": {
        "ok":  '#include <stdio.h>\nint main(){int a,b;scanf("%d %d",&a,&b);printf("%d",a+b);return 0;}',
        "wa":  '#include <stdio.h>\nint main(){printf("%d",-1);return 0;}',
        "ce":  '#include <stdio.h>\nint main(){int a = ;}',
        "rte": '#include <stdlib.h>\nint main(){abort();}',
        "tle": 'int main(){volatile long x=0;while(1)x++;}',
        "mle": '#include <stdlib.h>\n#include <string.h>\nint main(){for(long i=0;i<64;i++){char*p=malloc(64L*1024*1024);memset(p,1,64L*1024*1024);}return 0;}',
        "ole": '#include <stdio.h>\nint main(){for(long i=0;i<40000000L;i++)putchar(65);return 0;}',
    },
    "cpp11": {
        "ok":  '#include <iostream>\nint main(){int a,b;std::cin>>a>>b;std::cout<<a+b;}',
        "wa":  '#include <iostream>\nint main(){std::cout<<-1;}',
        "ce":  '#include <iostream>\nint main(){int a = ;}',
        "rte": '#include <stdexcept>\nint main(){throw std::runtime_error("boom");}',
        "tle": 'int main(){volatile long x=0;while(1)x++;}',
        "mle": '#include <vector>\nint main(){std::vector<char> v;for(long i=0;i<4L*1024*1024*1024;i++)v.push_back(1);return (int)v.size();}',
        "ole": '#include <cstdio>\nint main(){for(long i=0;i<40000000L;i++)putchar(65);}',
    },
    "cpp14": None,   # same family as cpp11 — filled from cpp11 at load
    "cpp":   None,
    "cpp20": None,
    "cpp23": None,
    "py3": {
        "ok":  'a,b=map(int,input().split());print(a+b)',
        "wa":  'print(-1)',
        "ce":  'def broken(:\n    pass',           # SyntaxError — py compiles to bytecode
        "rte": 'raise SystemExit(1)',
        "tle": 'x=0\nwhile True:\n    x+=1',
        "mle": "b=bytearray()\nwhile True:\n    b.extend(b'x'*(8*1024*1024))",
        "ole": "import sys\nfor _ in range(2000000):\n    sys.stdout.write('A'*32)",
    },
    "pypy3": None,   # same source as py3
    "java": {
        "ok":  'import java.util.*;\npublic class Main{public static void main(String[] a){Scanner s=new Scanner(System.in);System.out.print(s.nextInt()+s.nextInt());}}',
        "wa":  'public class Main{public static void main(String[] a){System.out.print(-1);}}',
        "ce":  'public class Main{public static void main(String[] a){int x = ;}}',
        "rte": 'public class Main{public static void main(String[] a){throw new RuntimeException("boom");}}',
        "tle": 'public class Main{public static void main(String[] a){long x=0;while(true)x++;}}',
        "mle": 'import java.util.*;\npublic class Main{public static void main(String[] a){List<byte[]> l=new ArrayList<>();while(true)l.add(new byte[8*1024*1024]);}}',
        "ole": 'public class Main{public static void main(String[] a){StringBuilder sb=new StringBuilder();for(int i=0;i<1000;i++)sb.append("A".repeat(1024));for(int i=0;i<40000;i++)System.out.print(sb);}}',
    },
    "kotlin": {
        "ok":  'fun main(){val (a,b)=readLine()!!.trim().split(" ").map{it.toInt()};print(a+b)}',
        "wa":  'fun main(){print(-1)}',
        "ce":  'fun main(){val x: Int = }',
        "rte": 'fun main(){throw RuntimeException("boom")}',
        "tle": 'fun main(){var x=0L;while(true)x++}',
        "mle": 'fun main(){val l=ArrayList<ByteArray>();while(true)l.add(ByteArray(8*1024*1024))}',
        "ole": 'fun main(){val s="A".repeat(1024);for(i in 0 until 40000)print(s.repeat(1000))}',
    },
    "rust": {
        "ok":  'use std::io::*;\nfn main(){let mut s=String::new();stdin().read_to_string(&mut s).unwrap();let v:Vec<i64>=s.split_whitespace().map(|x|x.parse().unwrap()).collect();print!("{}",v[0]+v[1]);}',
        "wa":  'fn main(){print!("{}",-1);}',
        "ce":  'fn main(){let x: i32 = ;}',
        "rte": 'fn main(){panic!("boom");}',
        "tle": 'fn main(){let mut x:u64=0;loop{x=x.wrapping_add(1);std::hint::black_box(x);}}',
        "mle": 'fn main(){let mut v:Vec<u8>=Vec::new();loop{v.extend(std::iter::repeat(1u8).take(8*1024*1024));}}',
        "ole": 'use std::io::*;\nfn main(){let o=stdout();let mut h=o.lock();let s=vec![b\'A\';1024];for _ in 0..40000{for _ in 0..1000{h.write_all(&s).unwrap();}}}',
    },
    "go": {
        "ok":  'package main\nimport "fmt"\nfunc main(){var a,b int;fmt.Scan(&a,&b);fmt.Print(a+b)}',
        "wa":  'package main\nimport "fmt"\nfunc main(){fmt.Print(-1)}',
        "ce":  'package main\nfunc main(){var x int = }',
        "rte": 'package main\nfunc main(){panic("boom")}',
        "tle": 'package main\nfunc main(){x:=0;for{x++;_=x}}',
        "mle": 'package main\nfunc main(){var s [][]byte;for{s=append(s,make([]byte,8*1024*1024))}}',
        "ole": 'package main\nimport ("bufio";"os")\nfunc main(){w:=bufio.NewWriter(os.Stdout);defer w.Flush();for i:=0;i<40000000;i++{w.WriteByte(65)}}',
    },
    "pascal": {
        "ok":  'var a,b:longint;begin readln(a,b); write(a+b); end.',
        "wa":  'begin write(-1); end.',
        "ce":  'begin write( end.',
        "rte": 'begin halt(1); end.',
        "tle": 'var x:int64;begin x:=0; while true do x:=x+1; end.',
        "mle": 'var p:pointer;i:longint;begin for i:=1 to 512 do getmem(p,8*1024*1024); end.',
        "ole": 'var i:longint;begin for i:=1 to 40000000 do write(\'A\'); end.',
    },
    "haskell": {
        "ok":  'main = do { s <- getContents; let ws = map read (words s) :: [Integer] in putStr (show (head ws + ws !! 1)) }',
        "wa":  'main = putStr "-1"',
        "ce":  'main = do { let x = }',
        "rte": 'main = error "boom"',
        "tle": 'loop :: Int -> Int\nloop n = loop (n+1)\nmain = print (loop 0)',
        # NOTE two GHC traps here. `length (replicate n x)` is fused away and
        # allocates nothing (returned WA). Retaining a 100M boxed-Int list does
        # allocate, but so slowly that the time limit trips first (returned TLE
        # even at 8s). A strict ByteString is a contiguous memset-speed
        # allocation, so the memory ceiling is what actually binds: MLE in
        # ~170ms at 412 MB measured.
        "mle": 'import qualified Data.ByteString as B\nmain = print (B.length (B.replicate (400*1024*1024) 65))',
        "ole": 'main = putStr (replicate 40000000 \'A\')',
    },
    "js": {
        "ok":  'const d=require("fs").readFileSync(0,"utf8").split(/\\s+/);process.stdout.write(String(+d[0]+ +d[1]));',
        "wa":  'process.stdout.write("-1");',
        "ce":  'function broken( {',
        "rte": 'process.exit(1);',
        "tle": 'let x=0;while(true)x++;',
        "mle": 'const a=[];while(true)a.push(Buffer.alloc(8*1024*1024));',
        "ole": 'const s="A".repeat(1024);for(let i=0;i<40000;i++)process.stdout.write(s.repeat(1000));',
    },
    "ruby": {
        "ok":  'a,b=gets.split.map(&:to_i);print a+b',
        "wa":  'print(-1)',
        "ce":  'def broken(\n',
        "rte": 'exit 1',
        "tle": 'x=0\nloop{x+=1}',
        "mle": 'a=[]\nloop{a << ("x"*(8*1024*1024))}',
        "ole": 's="A"*1024\n40000.times{ print s*1000 }',
    },
    "csharp": {
        "ok":  'using System;class P{static void Main(){var p=Console.ReadLine().Split(new[]{\' \'},StringSplitOptions.RemoveEmptyEntries);Console.Write(int.Parse(p[0])+int.Parse(p[1]));}}',
        "wa":  'using System;class P{static void Main(){Console.Write(-1);}}',
        "ce":  'using System;class P{static void Main(){int x = ;}}',
        "rte": 'using System;class P{static void Main(){throw new Exception("boom");}}',
        "tle": 'class P{static void Main(){long x=0;while(true)x++;}}',
        "mle": 'using System.Collections.Generic;class P{static void Main(){var l=new List<byte[]>();while(true)l.Add(new byte[8*1024*1024]);}}',
        "ole": 'using System;class P{static void Main(){var s=new string(\'A\',1024);for(int i=0;i<40000;i++)for(int j=0;j<1000;j++)Console.Write(s);}}',
    },
}

# C++ dialects share the cpp11 sources; pypy3 shares py3's.
for _alias in ("cpp14", "cpp", "cpp20", "cpp23"):
    PROGRAMS[_alias] = dict(PROGRAMS["cpp11"])
PROGRAMS["pypy3"] = dict(PROGRAMS["py3"])
# PyPy reaches the time limit before the memory limit when growing a bytearray
# 8 MB at a time (it returned TLE, not MLE). Fewer, larger allocations.
PROGRAMS["pypy3"]["mle"] = (
    "a = []\nwhile True:\n    a.append(bytearray(32 * 1024 * 1024))"
)

# Verdicts every language is expected to be able to reach.
VERDICTS = ("ok", "wa", "ce", "rte", "tle", "mle", "ole")

ALL_LANGUAGES = (
    "c", "cpp11", "cpp14", "cpp", "cpp20", "cpp23",
    "py3", "pypy3", "java", "kotlin", "rust", "go",
    "pascal", "haskell", "js", "ruby", "csharp",
)

# Aliases that must resolve to a canonical language.
ALIASES = {"cpp17": "cpp", "py": "py3"}
