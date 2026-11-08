/*
 * Real testlib checker used by the fixture test.
 *
 * Invocation (detected as the testlib contract):
 *   checker <input> <team_output> <answer>
 * Exit codes: 0 accepted, 1 wrong answer, 2 presentation error, 3 failure.
 */
#include "testlib.h"

int main(int argc, char *argv[]) {
    registerTestlibCmd(argc, argv);
    long long a = inf.readLong();
    long long b = inf.readLong();
    long long jury = ans.readLong();
    long long team = ouf.readLong();
    if (jury != a + b) {
        quitf(_fail, "jury answer is wrong: expected %lld, got %lld", a + b, jury);
    }
    if (team == a + b) {
        quitf(_ok, "correct sum");
    }
    quitf(_wa, "expected %lld, got %lld", a + b, team);
}
