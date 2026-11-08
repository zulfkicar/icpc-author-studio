/*
 * Real testlib interactor used by the fixture test.
 *
 * Protocol: the interactor sends n; the solution must answer 2*n.
 * Invocation (testlib-interactive contract):
 *   interactor <input> <transcript>
 */
#include "testlib.h"

using namespace std;

int main(int argc, char *argv[]) {
    registerInteraction(argc, argv);
    long long n = inf.readLong();
    cout << n << endl;
    cout.flush();
    long long answer = ouf.readLong();
    if (answer == 2 * n) {
        quitf(_ok, "correct answer");
    }
    quitf(_wa, "expected %lld, got %lld", 2 * n, answer);
}
