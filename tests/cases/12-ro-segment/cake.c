// Task 6: Read-Only Data Segment Verification

// .rodata (should be in RO segment)
const char* truth = "The cake is a lie";

// .data (should be in RW segment)
char buffer[64] = "I'm making a note here: HUGE SUCCESS.";

// .bss (should be in RW segment)
int cakes_eaten;

extern int printf(const char* fmt, ...);

int main()
{
    // We just print them to make sure they are linked correctly
    // The real check is in the layout verification
    printf("%s\n", truth);
    printf("%s\n", buffer);
    return 0;
}
