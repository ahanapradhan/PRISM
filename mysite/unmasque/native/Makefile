# Build the native PRISM backup/restore helper.
#
# libpq location can be overridden:
#   make PQ_PREFIX=/opt/homebrew/opt/libpq
#   make PQ_PREFIX=/usr/local/opt/libpq
# On Linux, PQ_PREFIX is usually empty (system libpq is in the default paths).

CC ?= cc
PQ_PREFIX ?= /opt/homebrew/opt/libpq

CFLAGS ?= -O2 -g -Wall -Wextra -std=c11 -pthread
CPPFLAGS += -I$(PQ_PREFIX)/include
LDFLAGS += -L$(PQ_PREFIX)/lib -Wl,-rpath,$(PQ_PREFIX)/lib
LDLIBS += -lpq -pthread

TARGET = pgcopy

all: $(TARGET)

$(TARGET): pgcopy.c
	$(CC) $(CPPFLAGS) $(CFLAGS) -o $@ $< $(LDFLAGS) $(LDLIBS)

clean:
	rm -f $(TARGET)

.PHONY: all clean
