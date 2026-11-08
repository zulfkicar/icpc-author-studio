/*
 * Real testlib transcript checker.
 *
 * The captured interaction transcript is passed as the team output file.
 * Transcript tokens are: "<" n ">" 2n  (judge line first, then solution line).
 */
#include "testlib.h"

int main(int argc, char *argv[]) {
    registerTestlibCmd(argc, argv);
    long long n = inf.readLong();
    std::string firstMarker = ouf.readToken();
    long long firstValue = ouf.readLong();
    std::string secondMarker = ouf.readToken();
    long long secondValue = ouf.readLong();
    if (firstMarker != "<" || firstValue != n) {
        quitf(_wa, "judge line is not the input value");
    }
    if (secondMarker != ">") {
        quitf(_wa, "solution line marker is missing");
    }
    if (secondValue != 2 * n) {
        quitf(_wa, "solution transcript value is wrong");
    }
    quitf(_ok, "transcript is consistent");
}
