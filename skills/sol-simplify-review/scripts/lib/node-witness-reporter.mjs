// Node's machine events identify the test itself; TAP's pass count may be a file wrapper.
export default async function* report(events) {
  for await (const { type, data } of events) {
    if (type !== 'test:pass' && type !== 'test:fail') continue;
    const error = data.details?.error;
    yield JSON.stringify({
      type, name: data.name, file: data.file, line: data.line,
      skip: data.skip ?? false, todo: data.todo ?? false,
      kind: data.details?.type,
      failure: error?.failureType,
      code: error?.cause?.code ?? error?.code,
      message: error?.cause?.message ?? error?.message,
    }) + '\n';
  }
}
