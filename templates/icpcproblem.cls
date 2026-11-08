\NeedsTeXFormat{LaTeX2e}
\ProvidesClass{icpcproblem}[2026/11/08 v1.0 ICPC-style problem statement class]

% Local ICPC-style class. The workspace did not contain a reusable ICPC
% class/style file on 2026-11-08. Replace this class with the official ICPC
% class if the contest toolchain provides one; keep the semantic section names.
\LoadClass[11pt,a4paper]{article}

\RequirePackage[T1]{fontenc}
\RequirePackage[utf8]{inputenc}
\RequirePackage{lmodern}
\RequirePackage[a4paper,margin=2.2cm,headheight=14pt]{geometry}
\RequirePackage{amsmath,amssymb}
\RequirePackage{graphicx}
\RequirePackage{xcolor}
\RequirePackage{listings}
\RequirePackage{fancyhdr}
\RequirePackage{hyperref}
\RequirePackage{enumitem}

\definecolor{icpcblue}{HTML}{1F4E79}
\definecolor{icpcgray}{HTML}{F2F2F2}

\hypersetup{colorlinks=true,linkcolor=icpcblue,urlcolor=icpcblue}
\setlength{\parindent}{0pt}
\setlength{\parskip}{0.55em}
\setlist[itemize]{topsep=0.3em,itemsep=0.15em,parsep=0pt}
\setlist[enumerate]{topsep=0.3em,itemsep=0.15em,parsep=0pt}

\lstset{
  basicstyle=\ttfamily\small,
  backgroundcolor=\color{icpcgray},
  frame=single,
  framerule=0.3pt,
  rulecolor=\color{black!25},
  breaklines=true,
  columns=fullflexible,
  keepspaces=true,
  showstringspaces=false,
  xleftmargin=0.6em,
  xrightmargin=0.6em,
  aboveskip=0.6em,
  belowskip=0.6em
}

\makeatletter
\def\@problemname{}
\def\@problemid{}
\def\@problemauthor{}
\def\@timelimit{}
\def\@memlimit{}
\def\@samplepath{../data/sample}

\newcommand{\problemname}[1]{\def\@problemname{#1}}
\newcommand{\problemid}[1]{\def\@problemid{#1}}
\newcommand{\problemauthor}[1]{\def\@problemauthor{#1}}
\newcommand{\timelimit}[1]{\def\@timelimit{#1}}
\newcommand{\memlimit}[1]{\def\@memlimit{#1}}
\newcommand{\samplepath}[1]{\def\@samplepath{#1}}

\pagestyle{fancy}
\fancyhf{}
\fancyhead[L]{\small\textsf{\@problemname}}
\fancyhead[R]{\small\textsf{\@problemid}}
\fancyfoot[C]{\small\thepage}
\renewcommand{\headrulewidth}{0.4pt}

\newcommand{\makeproblemhead}{%
  \begin{center}
    {\LARGE\bfseries\sffamily \@problemname\par}
    \vspace{0.4em}
    {\small\sffamily
      \@problemid
      \ifx\@timelimit\empty\else\quad Time limit: \@timelimit\fi
      \ifx\@memlimit\empty\else\quad Memory limit: \@memlimit\fi
    \par}
  \end{center}
  \vspace{0.4em}
}

% Sample inclusion. \samplepath points at the directory containing the sample
% .in/.ans files; \exinput{01.in} and \exoutput{01.ans} are the canonical calls.
\newcommand{\exinput}[1]{\lstinputlisting[caption={Sample Input}]{\@samplepath/#1}}
\newcommand{\exoutput}[1]{\lstinputlisting[caption={Sample Output}]{\@samplepath/#1}}

\newenvironment{ProblemDescription}{\section*{Problem Description}}{}
\newenvironment{Input}{\section*{Input}}{}
\newenvironment{Output}{\section*{Output}}{}
\newenvironment{Interaction}{\section*{Interaction Protocol}}{}
\newenvironment{Constraints}{\section*{Constraints}}{}
\newenvironment{Notes}{\section*{Notes}}{}
\newenvironment{Sample}{\section*{Sample}}{}
\makeatother

\endinput
