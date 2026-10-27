"""
Ask the agent one question from the command line:

    python -m finagent "What was Apple's revenue growth from 2022 to 2023?"
    python -m finagent -v "..."        # also print every tool call
"""
import argparse

from dotenv import load_dotenv

from . import agent


def main():
    load_dotenv()
    parser = argparse.ArgumentParser(prog='finagent')
    parser.add_argument('question')
    parser.add_argument('-v', '--verbose', action='store_true', help='print each tool call')
    parser.add_argument('--model', default=None)
    args = parser.parse_args()

    def show(step):
        print(f'  → {step["tool"]}({step["arguments"]})')
        if 'error' in step['result']:
            print(f'    ! {step["result"]["error"]}')

    result = agent.run(args.question, model=args.model, on_step=show if args.verbose else None)

    print()
    print(result.answer)
    print()
    if result.untraced:
        print(f'⚠ Numbers not traced to any tool result: {", ".join(result.untraced)}')
    print(f'[{len(result.steps)} tool calls · {result.model_calls} model calls · '
          f'{result.prompt_tokens + result.completion_tokens} tokens · {result.stopped}]')


if __name__ == '__main__':
    main()
